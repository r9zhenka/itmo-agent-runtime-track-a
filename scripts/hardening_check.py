"""Bounded, real-Docker hardening probes in disposable workspaces.

No LLM, external network or host stress workload. Resource exhaustion executes
only in capped containers. Independent Compose controller-crash acceptance is
performed separately by scripts.check_watchdog_crash in an isolated check-all stack.
"""
import argparse
import copy
import http.client
import json
import os
import shlex
import tempfile
import uuid
from pathlib import Path
from urllib.parse import quote

from client.api import settings
from client.workspace_server import WorkspaceServer
from runtime.docker_engine import Docker
from runtime.sandbox_manager import SandboxManager


def python_command(source):
    return "python -c " + shlex.quote(source)


# Raw text preserves the \n escapes inside the nested python -c worker string.
CPU = r"""import json,subprocess,sys,time
from pathlib import Path
def counters():
    return {k:int(v) for k,v in (line.split() for line in Path('/sys/fs/cgroup/cpu.stat').read_text().splitlines())}
before=counters(); started=time.monotonic()
code='import time\nend=time.monotonic()+3\nx=0\nwhile time.monotonic()<end: x=(x+1)%1000000'
workers=[subprocess.Popen([sys.executable,'-c',code]) for _ in range(4)]
for worker in workers: assert worker.wait()==0, 'CPU worker failed'
after=counters(); elapsed=time.monotonic()-started
print(json.dumps({'cpu_seconds':(after['usage_usec']-before['usage_usec'])/1000000,
                  'wall_seconds':elapsed,'throttled_periods':after['nr_throttled']-before['nr_throttled']}))
"""

PIDS = """import errno,json,subprocess,sys
from pathlib import Path
workers=[]; refused=False
before=int(Path('/sys/fs/cgroup/pids.events').read_text().split()[1])
try:
    for i in range(100):
        try: workers.append(subprocess.Popen([sys.executable,'-c','import time; time.sleep(15)']))
        except OSError as exc:
            refused=exc.errno==errno.EAGAIN
            break
    after=int(Path('/sys/fs/cgroup/pids.events').read_text().split()[1])
    print(json.dumps({'children':len(workers),'refused':refused,'limit_events':after-before}))
finally:
    for worker in workers: worker.terminate()
    for worker in workers: worker.wait()
"""

MEMORY = "blocks=[]\nfor _ in range(64): blocks.append(bytearray(16*1024*1024))"

FILE_LIMIT = """import errno,json,resource
limit=resource.getrlimit(resource.RLIMIT_FSIZE)[1]
failed=False
try:
    with open('bounded.bin','wb',buffering=0) as target:
        for _ in range(32): target.write(b'x'*65536)
except OSError as exc: failed=exc.errno==errno.EFBIG
print(json.dumps({'limit':limit,'rejected':failed}))
"""


class ProbeDocker(Docker):
    def create(self, config):
        config = copy.deepcopy(config)
        operation = config["Labels"].get("project-a.operation")
        # Tighten these two probes so they work on a one-vCPU VM and allocate only
        # one MiB on the host. The production bounds are separately asserted.
        if operation == "cpu":
            config["HostConfig"]["NanoCpus"] = 250_000_000
        if operation == "file":
            config["HostConfig"]["Ulimits"][0] = {"Name": "fsize", "Soft": 1048576, "Hard": 1048576}
        return super().create(config)


def containers(engine, instance):
    filters = quote(json.dumps({"label": [f"project-a.instance={instance}"]}))
    return engine.request("GET", "/containers/json?all=true&filters=" + filters)


def quota_probe(root):
    folder = root / "quota"
    folder.mkdir()
    exporter = WorkspaceServer(folder, max_bytes=10, max_entries=3)

    def request(method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", exporter.port, timeout=3)
        try:
            conn.request(method, path, body, {"Authorization": "Bearer " + exporter.token})
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()
    try:
        first = request("PUT", "/one", b"123456")
        second = request("PUT", "/two", b"12345")
        replacement = request("PUT", "/one", b"abcde")
        dirs = [request("MKCOL", "/" + name) for name in ("a", "b", "c")]
        return (first == 201 and second == replacement == 507 and dirs == [201, 201, 507]
                and (folder / "one").read_bytes() == b"123456"
                and not (folder / "two").exists() and not list(folder.glob(".agent-upload-*")))
    finally:
        exporter.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("results/hardening.json"))
    args = parser.parse_args()
    if os.getuid() == 0:
        raise SystemExit("Run as a non-root user with Docker access")
    workspaces = Path(settings().get("WORKSPACE_ROOT", "workspaces")).resolve()
    workspaces.mkdir(parents=True, exist_ok=True)
    instance = "hardening-" + uuid.uuid4().hex[:12]
    engine, records, completed = ProbeDocker(), [], False
    engine.ping()

    def require(name, condition, detail=None):
        records.append({"check": name, "passed": bool(condition), "detail": detail})
        if not condition:
            raise AssertionError(name + ": " + json.dumps(detail))
        print("PASS: " + name, flush=True)

    try:
        with tempfile.TemporaryDirectory(prefix="hardening-", dir=workspaces) as tmp:
            root = Path(tmp)
            folder = root / "work"
            folder.mkdir()
            manager = SandboxManager(engine, root, root, uid=os.getuid(), gid=os.getgid(),
                                     instance=instance, allow_local_rw=True)
            try:
                manager.provision("s", "work", "rw")

                def execute(operation, source):
                    return manager.exec("s", operation, "RunCommand", {"command": python_command(source)}, 20)

                result = execute("cpu", CPU)
                detail = json.loads(result["stdout"]) if result["exit_code"] == 0 else result
                require("CPU quota throttles real workload (0.25 CPU probe)",
                        result["exit_code"] == 0 and detail["throttled_periods"] > 0
                        and detail["cpu_seconds"] / detail["wall_seconds"] < 0.55, detail)
                result = execute("memory", MEMORY)
                require("RAM exhaustion is OOM-classified and container removed",
                        (result.get("error") or {}).get("kind") == "sandbox"
                        and (result.get("error") or {}).get("message") == "Memory limit exceeded"
                        and not containers(engine, instance), result)
                result = execute("pids", PIDS)
                detail = json.loads(result["stdout"]) if result["exit_code"] == 0 else result
                require("PID limit rejects bounded process storm", result["exit_code"] == 0
                        and detail["refused"] and 1 < detail["children"] < 64 and detail["limit_events"] > 0, detail)
                result = execute("file", FILE_LIMIT)
                detail = json.loads(result["stdout"]) if result["exit_code"] == 0 else result
                require("file-size kernel limit bounds local development writes", result["exit_code"] == 0
                        and detail["rejected"] and detail["limit"] == 1048576
                        and (folder / "bounded.bin").stat().st_size <= 1048576, detail)
                outside = root / "outside-secret.txt"
                outside.write_text("HOST-CANARY-DO-NOT-EXPOSE")
                (folder / "link").symlink_to(outside)
                result = manager.exec("s", "escape", "ReadFile", {"path": "link"}, 5)
                require("external symlink cannot expose host canary", result["exit_code"] != 0
                        and "HOST-CANARY" not in result["stdout"], result)
                source = "import os,socket,errno\nassert not any(k in os.environ for k in ('LLM_API_KEY','CLIENT_TOKEN','INTERNAL_TOKEN'))\nassert not os.path.exists('/var/run/docker.sock')\ns=socket.socket(); s.settimeout(1)\ntry: s.connect(('1.1.1.1',443)); raise AssertionError('network escaped')\nexcept OSError as e: assert e.errno==errno.ENETUNREACH\nfinally: s.close()\nprint('isolated')"
                result = execute("isolation", source)
                require("network socket and server secrets unavailable", result["exit_code"] == 0
                        and result["stdout"].strip() == "isolated", result)
                require("aggregate WebDAV bytes, entries and replacement staging bounded", quota_probe(root))
            finally:
                manager.close()
            require("all hardening containers removed", not containers(engine, instance))
        completed = True
    finally:
        cleanup_error = None
        try:
            engine.cleanup(instance)
        except Exception as exc:
            cleanup_error = exc
            records.append({"check": "final cleanup", "passed": False, "detail": type(exc).__name__})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"backend": "real Docker + HTTP WebDAV",
                                          "passed": completed and bool(records) and all(r["passed"] for r in records),
                                          "checks": records}, indent=2) + "\n")
        if cleanup_error is not None:
            raise cleanup_error


if __name__ == "__main__":
    main()
