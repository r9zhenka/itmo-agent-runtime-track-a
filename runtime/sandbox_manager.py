import json
import os
import threading
import time
from pathlib import Path

from .common import Fault, serve
from .contracts import SANDBOX, TOOLS, validate, validate_request
from .docker_engine import Docker


class SandboxManager:
    """A session owns /work; each command receives a fresh disposable container."""
    def __init__(self, engine, local_root, host_root, image="project-a-sandbox:cp1",
                 uid=1000, gid=1000, instance="checkpoint1"):
        self.engine = engine
        self.local_root = Path(local_root).resolve()
        self.host_root = Path(host_root)
        if not self.host_root.is_absolute():
            raise ValueError("WORKSPACE_ROOT must be an absolute Docker-host path")
        if uid <= 0 or gid <= 0:
            raise ValueError("Sandbox UID and GID must be non-root positive IDs")
        self.image, self.uid, self.gid, self.instance = image, uid, gid, instance
        self.sessions = {}
        self.lock = threading.RLock()

    def health(self):
        self.engine.ping()
        return {"status": "ok", "service": "sandbox-manager", "v": 0}

    def dispatch(self, body):
        op = validate_request(body, SANDBOX)
        args = {key: value for key, value in body.items() if key not in ("v", "op")}
        return getattr(self, op)(**args)

    def session(self, sid):
        with self.lock:
            if sid not in self.sessions:
                raise Fault("validation", "Unknown session", 404)
            return self.sessions[sid]

    def provision(self, session_id, workspace, mode):
        relative = Path(workspace)
        path = self.local_root / relative
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise Fault("validation", "Use a nonempty relative workspace path")
        resolved = path.resolve()
        if not resolved.is_relative_to(self.local_root) or resolved == self.local_root:
            raise Fault("validation", "Workspace escapes the configured root")
        if path != resolved or not path.is_dir():
            raise Fault("validation", "Workspace must be an existing directory without symlink components")
        signature = (str(relative), mode)
        with self.lock:
            if session_id in self.sessions:
                current = self.sessions[session_id]
                if current["signature"] != signature or current["released"]:
                    raise Fault("validation", "Session ID already used", 409)
                return {"v": 0, "session_id": session_id, "mode": mode}
            if len(self.sessions) >= 512:
                raise Fault("busy", "Session capacity reached; restart after releasing sessions", 429)
            for existing in self.sessions.values():
                other = existing["path"]
                if not existing["released"] and (path.is_relative_to(other) or other.is_relative_to(path)):
                    raise Fault("busy", "Workspace overlaps an active session", 409)
            self.sessions[session_id] = {
                "signature": signature, "path": path, "source": str(self.host_root / relative),
                "mode": mode, "cancel": threading.Event(), "released": False,
                "active": None, "operations": {}, "exec_lock": threading.Lock(),
            }
        return {"v": 0, "session_id": session_id, "mode": mode}

    def config(self, session, sid, opid, tool, arguments):
        if tool == "RunCommand":
            cmd = ["/bin/sh", "-lc", arguments["command"]]
        else:
            cmd = ["python", "/opt/file_tool.py", tool, json.dumps(arguments)]
        mounts = [{"Type": "bind", "Source": session["source"],
                   "Target": "/work", "ReadOnly": session["mode"] == "ro"}]
        if (session["path"] / ".git").exists():
            if (session["path"] / ".git").is_symlink():
                raise Fault("validation", "A symlink .git directory is unsupported")
            mounts.append({"Type": "bind", "Source": session["source"] + "/.git",
                           "Target": "/work/.git", "ReadOnly": True})
        return {
            "Image": self.image, "Cmd": cmd, "WorkingDir": "/work",
            "User": f"{self.uid}:{self.gid}", "Tty": False,
            "Env": ["PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/tmp", "LANG=C.UTF-8",
                    "PYTHONDONTWRITEBYTECODE=1", "PYTHONUNBUFFERED=1"],
            "Labels": {"project-a.instance": self.instance, "project-a.session": sid,
                       "project-a.operation": opid},
            "HostConfig": {
                "NetworkMode": "none", "ReadonlyRootfs": True,
                "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
                "Memory": 268435456, "MemorySwap": 268435456,
                "NanoCpus": 1_000_000_000, "PidsLimit": 64,
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=64m,mode=1777"},
                "Mounts": mounts, "Init": True,
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m", "max-file": "1"}},
            },
        }

    def exec(self, session_id, operation_id, tool, arguments, timeout_s):
        validate(arguments, TOOLS[tool], "arguments")
        session = self.session(session_id)
        signature = json.dumps([tool, arguments, timeout_s], sort_keys=True)
        if not session["exec_lock"].acquire(blocking=False):
            raise Fault("busy", "An operation is already running; retry the same ID", 409, True)
        started, cid = time.monotonic(), None
        result = {"v": 0, "type": "result", "session_id": session_id,
                  "operation_id": operation_id, "stdout": "", "stderr": "",
                  "exit_code": None, "error": None, "truncated": False}

        def check_status():
            if session["cancel"].is_set():
                raise Fault("cancelled", "Session cancelled", 409)
            if time.monotonic() - started >= timeout_s:
                raise Fault("timeout", "Command exceeded its deadline", 408)

        try:
            cached = session["operations"].get(operation_id)
            if cached:
                if cached[0] != signature:
                    raise Fault("validation", "Operation ID reused with different arguments", 409)
                return cached[1]
            if len(session["operations"]) >= 256:
                raise Fault("busy", "Operation capacity reached; create a new session", 429)
            if session["cancel"].is_set() or session["released"]:
                raise Fault("cancelled", "Session has been cancelled or released", 409)
            try:
                config = self.config(session, session_id, operation_id, tool, arguments)
                cid = self.engine.create(config)
                # Cancellation and publishing the active container are atomic.
                with self.lock:
                    session["active"] = cid
                    check_status()
                    self.engine.start(cid)
                while True:
                    check_status()
                    state = self.engine.inspect(cid)
                    check_status()
                    if not state["Running"]:
                        logs = self.engine.logs(cid)
                        check_status()
                        result.update(logs)
                        result["exit_code"] = state["ExitCode"]
                        if state.get("OOMKilled"):
                            result["error"] = {"kind": "sandbox", "message": "Memory limit exceeded", "retryable": False}
                        elif state["ExitCode"] != 0:
                            result["error"] = {"kind": "command", "message": "Nonzero exit code", "retryable": False}
                        break
                    session["cancel"].wait(0.05)
            except Fault as exc:
                result["error"] = (Fault("cancelled", "Session cancelled", 409)
                                   if session["cancel"].is_set() else exc).as_dict()["error"]
            finally:
                if cid:
                    try:
                        self.engine.remove(cid)  # Removes the complete process tree, including detached children.
                    except Fault:
                        result["error"] = {"kind": "sandbox", "message": "Container cleanup failed", "retryable": False}
                with self.lock:
                    session["active"] = None
            result["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
            session["operations"][operation_id] = (signature, result)
            return result
        finally:
            session["exec_lock"].release()

    def collect(self, session_id):
        session = self.session(session_id)
        if not session["exec_lock"].acquire(timeout=2):
            raise Fault("busy", "Operation still running", 409, True)
        try:
            return {"v": 0, "session_id": session_id,
                    "results": [{k: v for k, v in entry[1].items() if k not in ("stdout", "stderr")}
                                for entry in session["operations"].values()]}
        finally:
            session["exec_lock"].release()

    def cancel(self, session_id):
        session = self.session(session_id)
        with self.lock:
            session["cancel"].set()
            active = session["active"]
        if active:
            self.engine.remove(active)
        return {"v": 0, "session_id": session_id, "cancelled": True}

    def release(self, session_id):
        session = self.session(session_id)
        self.cancel(session_id)
        # Do not release the folder lock while an operation could still start a container.
        if not session["exec_lock"].acquire(timeout=25):
            raise Fault("busy", "Cleanup still in progress; retry release", 503, True)
        try:
            with self.lock:
                session["released"] = True
        finally:
            session["exec_lock"].release()
        return {"v": 0, "session_id": session_id, "released": True}

    def close(self):
        for sid in list(self.sessions):
            self.release(sid)
        self.engine.cleanup(self.instance)


def main():
    engine = Docker(os.getenv("DOCKER_SOCKET", "/var/run/docker.sock"))
    instance = os.getenv("INSTANCE_ID", "checkpoint1")
    engine.cleanup(instance)  # Recover containers left by an interrupted manager.
    app = SandboxManager(engine, "/workspaces", os.environ["WORKSPACE_ROOT"],
                         os.getenv("SANDBOX_IMAGE", "project-a-sandbox:cp1"),
                         int(os.getenv("SANDBOX_UID", "1000")),
                         int(os.getenv("SANDBOX_GID", "1000")), instance)
    serve(app, os.environ["INTERNAL_TOKEN"])


if __name__ == "__main__":
    main()
