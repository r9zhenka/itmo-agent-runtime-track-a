import json
import os
import threading
import time
from pathlib import Path

from .common import Fault, serve
from .contracts import SANDBOX, TOOLS, validate, validate_request
from .docker_engine import Docker
from .mount_lease import check_lease, lease_name


class SandboxManager:
    """A session owns /work; each command receives a fresh disposable container."""
    def __init__(self, engine, local_root, host_root, image="project-a-sandbox:cp1",
                 uid=1000, gid=1000, instance="checkpoint1", allow_local_rw=False):
        self.engine = engine
        self.local_root = Path(local_root).resolve()
        self.host_root = Path(host_root)
        if not self.host_root.is_absolute():
            raise ValueError("WORKSPACE_ROOT must be an absolute Docker-host path")
        if uid <= 0 or gid <= 0:
            raise ValueError("Sandbox UID and GID must be non-root positive IDs")
        self.image, self.uid, self.gid, self.instance = image, uid, gid, instance
        self.allow_local_rw = allow_local_rw
        self.sessions = {}
        self.lock = threading.RLock()

    def health(self):
        self.engine.ping()
        return {"status": "ok", "service": "sandbox-manager", "v": 0}

    def dispatch(self, body):
        op = validate_request(body, SANDBOX)
        args = {key: value for key, value in body.items() if key not in ("v", "op")}
        result = getattr(self, op)(**args)
        return {"v": 0, "events": result} if op == "events" else result

    def session(self, sid):
        with self.lock:
            if sid not in self.sessions:
                raise Fault("validation", "Unknown session", 404)
            return self.sessions[sid]

    def provision(self, session_id, workspace, mode):
        check_lease(self.local_root, workspace, mode)
        if mode == "rw" and lease_name(workspace) is None and not self.allow_local_rw:
            raise Fault("validation", "Local read-write bind mounts require explicit ALLOW_LOCAL_RW=1 for trusted development; use a quota-controlled remote folder", 403)
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
            closed = [sid for sid, state in self.sessions.items() if state["released"]]
            for old_sid in closed[:max(0, len(closed) - 128)]:
                del self.sessions[old_sid]
            if sum(not state["released"] for state in self.sessions.values()) >= 512:
                raise Fault("busy", "Active session capacity reached; release a session", 429)
            for existing in self.sessions.values():
                other = existing["path"]
                if not existing["released"] and (path.is_relative_to(other) or other.is_relative_to(path)):
                    raise Fault("busy", "Workspace overlaps an active session", 409)
            self.sessions[session_id] = {
                "sid": session_id, "signature": signature, "path": path, "source": str(self.host_root / relative),
                "mode": mode, "cancel": threading.Event(), "released": False,
                "remote_workspace": lease_name(workspace),
                "active": None, "operations": {}, "exec_lock": threading.Lock(),
                "cleanup_lock": threading.Lock(), "pending": None,
                "events": [], "event_condition": threading.Condition(self.lock),
                "cursors": {},
            }
        return {"v": 0, "session_id": session_id, "mode": mode}

    def emit(self, session, operation_id, kind, **payload):
        with self.lock:
            event = {"v": 0, "seq": len(session["events"]) + 1,
                     "session_id": session["sid"], "operation_id": operation_id,
                     "type": kind, **payload}
            session["events"].append(event)
            session["event_condition"].notify_all()

    def events(self, session_id, after):
        session = self.session(session_id)
        with session["event_condition"]:
            if type(after) is not int or not 0 <= after <= len(session["events"]):
                raise Fault("validation", "Invalid sandbox event cursor")
            if after == len(session["events"]):
                session["event_condition"].wait(0.5)
            return session["events"][after:after + 4]

    def start(self, session_id, operation_id, tool, arguments, timeout_s):
        """Accept one operation; events carry progress and exactly one terminal result.

        Same-ID retries return the same cursor without reexecuting side effects.
        A distinct operation is rejected while this session has an active operation.
        """
        validate(arguments, TOOLS[tool], "arguments")
        session = self.session(session_id)
        signature = json.dumps([tool, arguments, timeout_s], sort_keys=True)
        with self.lock:
            existing = session["operations"].get(operation_id)
            pending = session["pending"]
            if existing is not None:
                if existing[0] != signature:
                    raise Fault("validation", "Operation ID reused with different arguments", 409)
            elif pending is not None:
                if pending["id"] != operation_id:
                    raise Fault("busy", "An operation is already running", 409, True)
                if pending["signature"] != signature:
                    raise Fault("validation", "Operation ID reused with different arguments", 409)
            else:
                if session["cancel"].is_set() or session["released"]:
                    raise Fault("cancelled", "Session has been cancelled or released", 409)
                if session["exec_lock"].locked():
                    raise Fault("busy", "An operation is already running", 409, True)
                if len(session["operations"]) >= 256:
                    raise Fault("busy", "Operation capacity reached; create a new session", 429)
                pending = {"id": operation_id, "signature": signature}
                session["pending"] = pending
                session["cursors"][operation_id] = len(session["events"])

                def work():
                    try:
                        self.exec(session_id, operation_id, tool, arguments, timeout_s, _reservation=pending)
                    except Exception as exc:
                        fault = exc if isinstance(exc, Fault) else Fault("sandbox", "Operation worker failed", 500)
                        with self.lock:
                            if operation_id not in session["operations"]:
                                result = {"v": 0, "type": "result", "session_id": session_id,
                                          "operation_id": operation_id, "stdout": "", "stderr": "",
                                          "exit_code": None, "error": fault.as_dict()["error"],
                                          "duration_ms": 0, "truncated": False}
                                session["operations"][operation_id] = (signature, result)
                                self.emit(session, operation_id, "result", result=result)
                    finally:
                        with self.lock:
                            if session["pending"] is pending:
                                session["pending"] = None
                thread = threading.Thread(target=work, daemon=True)
                pending["thread"] = thread
                try:
                    thread.start()
                except Exception:
                    # No worker was launched: undo acceptance state so release
                    # remains possible and a same-ID retry can safely start once.
                    session["pending"] = None
                    del session["cursors"][operation_id]
                    raise Fault("sandbox", "Cannot start sandbox operation worker", 503, True) from None
            return {"v": 0, "session_id": session_id, "operation_id": operation_id,
                    "accepted": True, "after": session["cursors"].get(operation_id, 0)}

    def config(self, session, sid, opid, tool, arguments, deadline=None):
        if tool == "RunCommand":
            cmd = ["/bin/sh", "-lc", arguments["command"]]
        else:
            cmd = ["python", "/opt/file_tool.py", tool, json.dumps(arguments)]
        mounts = [{"Type": "bind", "Source": session["source"],
                   "Target": "/work", "ReadOnly": session["mode"] == "ro"}]
        if not session["remote_workspace"] and (session["path"] / ".git").exists():
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
                       "project-a.operation": opid,
                       "project-a.workspace": session["remote_workspace"] or "local",
                       "project-a.mode": session["mode"], "project-a.guard": "v1",
                       "project-a.deadline": str(deadline if deadline is not None else time.time() + 120)},
            "HostConfig": {
                "NetworkMode": "none", "ReadonlyRootfs": True,
                "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges:true"],
                "Memory": 268435456, "MemorySwap": 268435456,
                "NanoCpus": 1_000_000_000, "PidsLimit": 64,
                "Ulimits": [{"Name": "fsize", "Soft": 128 * 1024 * 1024, "Hard": 128 * 1024 * 1024},
                            {"Name": "nofile", "Soft": 256, "Hard": 256}],
                "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=64m,mode=1777"},
                "Mounts": mounts, "Init": True,
                "LogConfig": {"Type": "json-file", "Config": {"max-size": "1m", "max-file": "1"}},
            },
        }

    def _remove_container(self, session, cid):
        # cancel() and exec() may both request cleanup. Only one DELETE may run;
        # Docker can return HTTP 409 while another removal is in progress.
        with session["cleanup_lock"]:
            with self.lock:
                if session["active"] != cid:
                    return
            self.engine.remove(cid)  # Includes detached child processes.
            with self.lock:
                session["active"] = None

    def exec(self, session_id, operation_id, tool, arguments, timeout_s, _reservation=None):
        validate(arguments, TOOLS[tool], "arguments")
        session = self.session(session_id)
        signature = json.dumps([tool, arguments, timeout_s], sort_keys=True)
        with self.lock:
            if session["pending"] is not None and session["pending"] is not _reservation:
                raise Fault("busy", "An operation is already running; retry the same ID", 409, True)
            if not session["exec_lock"].acquire(blocking=False):
                raise Fault("busy", "An operation is already running; retry the same ID", 409, True)
        started, cid = time.monotonic(), None
        publish_terminal = False
        result = {"v": 0, "type": "result", "session_id": session_id,
                  "operation_id": operation_id, "stdout": "", "stderr": "",
                  "exit_code": None, "error": None, "truncated": False}

        def check_status():
            if session["remote_workspace"]:
                check_lease(self.local_root, session["remote_workspace"], session["mode"])
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
            if session["active"] is not None:
                raise Fault("sandbox", "Previous container cleanup failed; release the session", 503)
            with self.lock:
                session["cursors"].setdefault(operation_id, len(session["events"]))
            self.emit(session, operation_id, "started", tool=tool)
            try:
                check_status()
                config = self.config(session, session_id, operation_id, tool, arguments,
                                     deadline=time.time() + max(0, timeout_s - (time.monotonic() - started)))
                cid = self.engine.create(config)
                # Cancellation and publishing the active container are atomic.
                with self.lock:
                    session["active"] = cid
                    check_status()
                    self.engine.start(cid)
                self.emit(session, operation_id, "running", tool=tool)
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
                # The independent reaper may remove a container between status
                # checks and Docker inspection. Preserve the deadline/lease cause
                # instead of turning a successful cleanup into an opaque 404.
                try:
                    check_status()
                except Fault as status_error:
                    exc = status_error
                result["error"] = (Fault("cancelled", "Session cancelled", 409)
                                   if session["cancel"].is_set() else exc).as_dict()["error"]
            finally:
                if cid:
                    try:
                        self._remove_container(session, cid)
                    except Fault:
                        result["error"] = {"kind": "sandbox", "message": "Container cleanup failed", "retryable": False}
            result["duration_ms"] = round((time.monotonic() - started) * 1000, 3)
            with self.lock:
                session["operations"][operation_id] = (signature, result)
                publish_terminal = True
            return result
        finally:
            with self.lock:
                session["exec_lock"].release()
                if _reservation is not None and session["pending"] is _reservation:
                    session["pending"] = None
                if publish_terminal:
                    self.emit(session, operation_id, "result", result=result)

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
            self._remove_container(session, active)
        return {"v": 0, "session_id": session_id, "cancelled": True}

    def release(self, session_id):
        session = self.session(session_id)
        self.cancel(session_id)
        with self.lock:
            pending = session["pending"]
        if pending is not None:
            pending["thread"].join(timeout=25)
            if pending["thread"].is_alive():
                raise Fault("busy", "Operation cleanup still in progress; retry release", 503, True)
        # Do not release the folder lock while an operation could still start a container.
        if not session["exec_lock"].acquire(timeout=25):
            raise Fault("busy", "Cleanup still in progress; retry release", 503, True)
        try:
            # An in-flight create may have published a container after cancel().
            if session["active"] is not None:
                self._remove_container(session, session["active"])
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
                         int(os.getenv("SANDBOX_GID", "1000")), instance,
                         allow_local_rw=os.getenv("ALLOW_LOCAL_RW", "0") == "1")
    serve(app, os.environ["INTERNAL_TOKEN"])


if __name__ == "__main__":
    main()
