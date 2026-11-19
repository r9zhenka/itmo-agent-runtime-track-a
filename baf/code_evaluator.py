"""Grade generated functions using a fresh sandbox container for each input.

The production runner always uses Docker. Tests may explicitly inject their
trusted fixture engine; there is no automatic local-execution fallback.
"""
import json
import os
import shlex
import tempfile
import time
import uuid
from pathlib import Path

from baf.code_checks import checks
from baf.artifacts import read_file
from runtime.common import Fault
from runtime.docker_engine import Docker
from runtime.sandbox_manager import SandboxManager


def read_solution(workspace, source_file="solution.py"):
    source = read_file(workspace, source_file)
    if not source:
        raise ValueError("Submitted source must contain 1..65536 bytes")
    return source


def same_json(actual, expected):
    # Python's ordinary equality would accept True for 1 and 1.0 for 1.
    options = {"sort_keys": True, "separators": (",", ":"), "allow_nan": False}
    return json.dumps(actual, **options) == json.dumps(expected, **options)


class FunctionEvaluator:
    def __init__(self, engine=None, image="project-a-sandbox:cp1", timeout=5):
        self.engine = engine if engine is not None else Docker()
        self.backend = "docker" if isinstance(self.engine, Docker) else "test-only-fixture"
        self.image, self.timeout = image, timeout

    def check(self, identifier, workspace, source_file="solution.py"):
        started = time.monotonic()
        function, vectors = checks(identifier)
        results, failure = [], None
        try:
            source = read_solution(workspace, source_file)  # Never compile/import on host.
            if os.getuid() == 0:
                raise ValueError("Run the benchmark as a non-root user with Docker access")
            self.engine.ping()
            with tempfile.TemporaryDirectory(prefix="baf-code-") as tmp:
                root = Path(tmp)
                snapshot = root / "snapshot"
                snapshot.mkdir()
                (snapshot / "solution.py").write_bytes(source)
                (snapshot / "solution.py").chmod(0o444)
                manager = SandboxManager(self.engine, root, root, image=self.image,
                                         uid=os.getuid(), gid=os.getgid(), instance="baf-check-" + uuid.uuid4().hex)
                try:
                    manager.provision("check", "snapshot", "ro")
                    for index, (name, value, expected) in enumerate(vectors):
                        # Only input reaches the container. Expected answers stay here.
                        command = shlex.join(["python", "-I", "/opt/code_worker.py", function,
                                              json.dumps(value, ensure_ascii=True)])
                        result = manager.exec("check", f"input-{index}", "RunCommand", {"command": command}, self.timeout)
                        reason = "ok"
                        error = result.get("error") or {}
                        if error or result.get("exit_code") != 0:
                            reason = "execution: " + error.get("kind", "invalid exit status")
                        elif result.get("truncated"):
                            reason = "output exceeded limit"
                        else:
                            try:
                                reply = json.loads(result["stdout"])
                                if not isinstance(reply, dict) or set(reply) != {"value"}:
                                    raise ValueError()
                                if not same_json(reply["value"], expected):
                                    reason = "incorrect return value"
                            except (ValueError, TypeError, KeyError, RecursionError):
                                reason = "invalid result JSON"
                        results.append({"name": name, "pass": reason == "ok", "reason": reason})
                        if error.get("kind") in ("timeout", "sandbox", "transport", "cancelled"):
                            # Don't spend the whole suite repeatedly executing a hung/broken candidate.
                            break
                finally:
                    manager.close()
        except (Fault, OSError, ValueError) as exc:
            failure = str(exc)
        passed = sum(item["pass"] for item in results)
        success = failure is None and passed == len(vectors)
        return {"pass": success, "reason": "ok" if success else failure or f"Hidden checks passed: {passed}/{len(vectors)}",
                "checker_backend": self.backend, "checks_passed": passed, "checks_total": len(vectors),
                "checks_run": len(results), "checks": results,
                "check_ms": round((time.monotonic() - started) * 1000, 3)}
