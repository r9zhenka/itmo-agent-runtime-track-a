"""Real-container checks. Requires the Compose images and Docker socket access.

Unlike unittest's FixtureProcessEngine, these checks exercise actual isolation.
They create only labelled disposable containers and a fresh workspace directory.
"""
import json
import os
import threading
import time
import uuid
from pathlib import Path

from client.api import settings
from runtime.docker_engine import Docker
from runtime.sandbox_manager import SandboxManager


# Keep diagnostics on the Docker log stream, outside the tmpfs being filled.
TEMP_DISK_COMMAND = "dd if=/dev/zero of=/tmp/fill bs=1048576 count=80"


def command_failed(result):
    """An isolation check must observe a command failure, not a broken executor."""
    code = result.get("exit_code")
    return (type(code) is int and code != 0
            and (result.get("error") or {}).get("kind") == "command")


def temporary_disk_full(result):
    return command_failed(result) and "No space left on device" in result.get("stderr", "")


def main():
    config = settings()
    root = Path(config.get("WORKSPACE_ROOT", "workspaces")).resolve()
    name = "docker-check-" + uuid.uuid4().hex[:10]
    folder = root / name
    folder.mkdir(parents=True)
    (folder / ".git").mkdir()
    (folder / ".git/config").write_text("protected\n")
    (folder / "client.txt").write_text("from client\n")
    engine = Docker()
    engine.ping()
    instance = "check-" + uuid.uuid4().hex
    manager = SandboxManager(engine, root, root, uid=os.getuid(), gid=os.getgid(), instance=instance)
    results = []

    def execute(command, timeout=5):
        result = manager.exec("rw", uuid.uuid4().hex, "RunCommand", {"command": command}, timeout)
        return result

    def require(name, condition, detail=None):
        record = {"check": name, "pass": bool(condition), "backend": "docker"}
        if detail is not None:
            record["detail"] = detail
        results.append(record)
        if not condition:
            raise AssertionError(name + (": " + json.dumps(detail) if detail is not None else ""))
        print("PASS: " + name, flush=True)

    try:
        manager.provision("rw", name, "rw")
        result = execute("cat client.txt; echo agent > agent.txt")
        require("bidirectional bind mount", result["exit_code"] == 0 and "from client" in result["stdout"] and (folder / "agent.txt").read_text().strip() == "agent")
        require("non-root user", execute("id -u")["stdout"].strip() == str(os.getuid()) and os.getuid() != 0)
        # /etc is already unwritable to our user even on a writable root; inspect
        # the filesystem flag so an ordinary permissions failure cannot pass.
        readonly = execute("python -c 'import os; print(bool(os.statvfs(\"/\").f_flag & os.ST_RDONLY))'")
        require("read-only root filesystem", readonly["exit_code"] == 0 and readonly["stdout"].strip() == "True")
        require("protected .git", command_failed(execute("echo changed > .git/config")) and (folder / ".git/config").read_text() == "protected\n")
        require("network namespace has only loopback", execute("python -c 'import socket; print([n for _,n in socket.if_nameindex()])'")["stdout"].strip() == "['lo']")
        require("no server secrets", execute("python -c 'import os; assert not any(k in os.environ for k in (\"LLM_API_KEY\",\"INTERNAL_TOKEN\",\"CLIENT_TOKEN\"))'")["exit_code"] == 0)
        resource = execute("python -c 'from pathlib import Path; print(Path(\"/sys/fs/cgroup/memory.max\").read_text().strip()); print(Path(\"/sys/fs/cgroup/pids.max\").read_text().strip()); print(Path(\"/sys/fs/cgroup/cpu.max\").read_text().strip())'")
        require("cgroup v2 resource settings", resource["exit_code"] == 0 and resource["stdout"].splitlines()[:2] == ["268435456", "64"] and resource["stdout"].splitlines()[2] == "100000 100000")
        disk = execute(TEMP_DISK_COMMAND)
        require("bounded temporary disk", temporary_disk_full(disk), detail=disk)
        require("operation timeout", execute("sleep 10", timeout=0.5)["error"]["kind"] == "timeout")
        result = execute("echo OK; echo failed >&2; exit 1")
        require("command error classification", result["exit_code"] == 1 and result["error"]["kind"] == "command" and result["stdout"] == "OK\n")
        workers = []
        worker = threading.Thread(target=lambda: workers.append(execute("(sleep 2; echo leaked > leaked.txt) & wait", timeout=10)))
        worker.start()
        deadline = time.monotonic() + 5
        while not manager.session("rw")["active"] and time.monotonic() < deadline:
            time.sleep(0.02)
        manager.cancel("rw")
        worker.join(timeout=15)
        time.sleep(2.1)
        require("cancel kills process tree", not worker.is_alive() and bool(workers) and workers[0]["error"]["kind"] == "cancelled" and not (folder / "leaked.txt").exists())
        manager.release("rw")
        manager.provision("ro", name, "ro")
        result = manager.exec("ro", "write", "WriteFile", {"path": "forbidden.txt", "content": "no"}, 5)
        require("read-only workspace", command_failed(result) and not (folder / "forbidden.txt").exists())
        manager.release("ro")
        from urllib.parse import quote
        filters = quote(json.dumps({"label": [f"project-a.instance={instance}"]}))
        require("no leftover containers", engine.request("GET", "/containers/json?all=true&filters=" + filters) == [])
    finally:
        manager.close()
        target = Path("results/docker-check.json")
        target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(results, indent=2) + "\n")
    print("Actual Docker checks completed. Results: results/docker-check.json")


if __name__ == "__main__":
    main()
