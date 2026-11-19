"""Real-Docker acceptance of B6 grading, without a model or Compose services."""
import json
import os
import tempfile
from pathlib import Path

from baf.code_cases import REFERENCES
from baf.code_evaluator import FunctionEvaluator
from runtime.common import Fault
from runtime.docker_engine import Docker


class TrackingDocker(Docker):
    def __init__(self):
        super().__init__()
        self.ids = []

    def create(self, config):
        cid = super().create(config)
        self.ids.append(cid)
        return cid


def main():
    engine = TrackingDocker()
    evaluator = FunctionEvaluator(engine)
    records = []
    completed = False
    os.environ["B6_HOST_CANARY"] = "must-not-reach-checked-code"

    def run(name, identifier, source, expected, expected_reason=None):
        with tempfile.TemporaryDirectory(prefix="baf-accept-") as tmp:
            path = Path(tmp) / "solution.py"
            path.write_text(source)
            result = evaluator.check(identifier, tmp)
            passed = result["pass"] == expected and path.read_text() == source
            if not expected:
                # An unavailable executor must not masquerade as rejecting bad code.
                passed &= bool(result["checks"]) and all(item["reason"] == expected_reason for item in result["checks"])
            records.append({"name": name, "passed": passed, "verdict": result})
            if not passed:
                raise AssertionError(json.dumps(records[-1]))
            print("PASS: " + name, flush=True)
        return result

    try:
        for identifier, source in REFERENCES.items():
            run(identifier + " correct", identifier, source, True)
        run("incorrect function rejected", "B6.1", "def slugify(text): return 42\n", False, "incorrect return value")
        run("fake pass report rejected", "B6.1", "import os\nprint('{\"pass\":true}', flush=True)\nos._exit(0)\n", False, "invalid result JSON")
        run("readonly solution", "B6.1", "from pathlib import Path\nPath('solution.py').write_text('tampered')\n", False, "execution: command")
        secured = ("import os, socket\n"
                   "assert not any(k in os.environ for k in ('B6_HOST_CANARY','LLM_API_KEY','CLIENT_TOKEN','INTERNAL_TOKEN'))\n"
                   "assert [name for _,name in socket.if_nameindex()] == ['lo']\n" + REFERENCES["B6.1"])
        run("network and secret isolation", "B6.1", secured, True)
        evaluator.timeout = 1
        result = run("timeout cleanup", "B6.1", "def slugify(text):\n    while True: pass\n", False, "execution: timeout")
        if result["checks"][0]["reason"] != "execution: timeout":
            raise AssertionError("Expected actual timeout")
        for cid in engine.ids:
            try:
                engine.inspect(cid)
            except Fault as exc:
                if "HTTP 404" not in exc.message:
                    raise
            else:
                raise AssertionError("Checker container was not removed")
        print("PASS: no checker containers remain", flush=True)
        records.append({"name": "no checker containers remain", "passed": True})
        completed = True
    finally:
        output = Path("results/b6-checker.json")
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps({"backend": "docker", "passed": completed, "checks": records}, indent=2) + "\n")


if __name__ == "__main__":
    main()
