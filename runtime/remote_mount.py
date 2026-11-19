"""Host-side FUSE supervisor, started through SSH by client.remote.

Runs on the Linux Docker host as its normal user, outside Compose. Only JSON
control messages go to stdout. Workspace contents never enter the control channel.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from .common import Fault, Remote, request_json
from .mount_lease import CONTROL, PREFIX, TTL, write_lease

RCLONE_VERSION = "v1.68.2"


def host_settings(path=".env"):
    wanted = {"WORKSPACE_ROOT", "SANDBOX_UID", "SANDBOX_GID", "GATEWAY_PORT"}
    result = {}
    for line in Path(path).read_text().splitlines():
        key, sep, value = line.partition("=")
        if sep and key in wanted:
            result[key] = value.strip().strip("\"'")
    return result


def rclone_binary():
    pinned = Path.home() / ".local/bin/rclone"
    return str(pinned) if pinned.is_file() else "rclone"


def mount_command(path, mode, uid, gid):
    args = [rclone_binary(), "mount", ":webdav:", str(path), "--config", "/dev/null",
            "--allow-other", "--default-permissions", "--uid", str(uid), "--gid", str(gid),
            "--file-perms", "0600", "--dir-perms", "0700", "--vfs-cache-mode", "off",
            "--dir-cache-time", "0s", "--attr-timeout", "0s", "--buffer-size", "0",
            "--poll-interval", "0", "--timeout", "5s", "--contimeout", "3s",
            "--retries", "1", "--low-level-retries", "1", "--no-modtime",
            "--log-level", "ERROR"]
    if mode == "ro":
        args.append("--read-only")
    return args


def check_dependencies():
    for binary in (rclone_binary(), "fusermount3"):
        if not shutil.which(binary):
            raise RuntimeError(f"Install {binary} on the server; see docs/remote-mount.md")
    if not Path("/dev/fuse").exists():
        raise RuntimeError("The server needs /dev/fuse; see docs/remote-mount.md")
    output = subprocess.check_output([rclone_binary(), "version"], text=True, timeout=5)
    if output.splitlines()[0] != "rclone " + RCLONE_VERSION:
        raise RuntimeError("Expected rclone " + RCLONE_VERSION + "; see docs/remote-mount.md")


def probe(url, token):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url + ".agent-health", headers={"Authorization": "Bearer " + token})
    with opener.open(request, timeout=3) as response:
        if response.read(64) != b"workspace-v1":
            raise RuntimeError("Unexpected workspace endpoint")


class MountedFolder:
    def __init__(self, root, mode, url, token, uid, gid):
        self.root, self.mode = Path(root).resolve(strict=True), mode
        self.url, self.token, self.uid, self.gid = url, token, uid, gid
        self.workspace = PREFIX + uuid.uuid4().hex
        self.path = self.root / self.workspace
        self.process = None
        self.created = False
        self.underlying_fd = None

    def start(self):
        check_dependencies()
        probe(self.url, self.token)
        self.path.mkdir(mode=0o700)
        self.created = True
        # Keep a descriptor of the underlying directory, not the FUSE root.
        self.underlying_fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
        env = {k: v for k, v in os.environ.items() if not k.startswith("RCLONE_")}
        env.update(RCLONE_WEBDAV_URL=self.url, RCLONE_WEBDAV_VENDOR="other",
                   RCLONE_WEBDAV_BEARER_TOKEN=self.token)
        self.process = subprocess.Popen(mount_command(self.path, self.mode, self.uid, self.gid),
                                        env=env, stdin=subprocess.DEVNULL,
                                        stdout=subprocess.DEVNULL, stderr=sys.stderr)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("rclone mount failed; check /etc/fuse.conf and the server log")
            if os.path.ismount(self.path):
                # Fail closed even if FUSE vanishes between lease check and Docker bind.
                os.fchmod(self.underlying_fd, 0)
                self.renew()
                return
            time.sleep(0.05)
        raise RuntimeError("Timed out mounting the client folder")

    def renew(self):
        if self.process.poll() is not None or not os.path.ismount(self.path):
            raise RuntimeError("Remote filesystem mount stopped")
        probe(self.url, self.token)
        write_lease(self.root, self.workspace, self.mode, time.time() + TTL)

    def revoke(self):
        if self.created:
            write_lease(self.root, self.workspace, self.mode, 0)

    def close(self):
        if not self.created:
            return
        failure = None
        try:
            self.revoke()
        except Exception as exc:
            failure = exc
        try:
            if os.path.ismount(self.path):
                result = subprocess.run(["fusermount3", "-u", str(self.path)], capture_output=True, timeout=8)
                if result.returncode:
                    # Detach stale handles; killing rclone below makes their I/O fail.
                    subprocess.run(["fusermount3", "-uz", str(self.path)], check=True,
                                   capture_output=True, timeout=8)
        except Exception as exc:
            failure = exc
        finally:
            try:
                if self.process is not None:
                    if self.process.poll() is None:
                        self.process.terminate()
                    try:
                        self.process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=3)
            finally:
                if self.underlying_fd is not None:
                    os.close(self.underlying_fd)
                    self.underlying_fd = None
        if failure is not None:
            raise failure
        if os.path.ismount(self.path):
            raise RuntimeError("Mount is still attached")
        self.path.rmdir()  # Never recursively delete a mounted user's folder.
        (self.root / CONTROL / (self.workspace + ".json")).unlink(missing_ok=True)
        self.created = False


def emit(value):
    try:
        print(json.dumps(value), flush=True)
    except (BrokenPipeError, OSError):
        # SSH loss must not interrupt the finally block which releases/unmounts.
        pass


def main():
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    mount, sid, rpc = None, None, None
    failed = False
    try:
        body = json.loads(sys.stdin.readline(16384))
        port, mode = body["port"], body["mode"]
        if type(port) is not int or not 1024 <= port <= 65535 or mode not in ("ro", "rw"):
            raise ValueError("Invalid mount parameters")
        if not isinstance(body["mount_token"], str) or len(body["mount_token"]) < 32:
            raise ValueError("Invalid mount credential")
        config = host_settings()
        uid, gid = int(config.get("SANDBOX_UID", "1000")), int(config.get("SANDBOX_GID", "1000"))
        if uid <= 0 or gid <= 0:
            raise ValueError("Sandbox must be non-root")
        gateway = "http://127.0.0.1:" + config.get("GATEWAY_PORT", "18080")
        rpc = Remote(gateway, body["client_token"], timeout=10)
        health = request_json(gateway + "/health", timeout=5)
        if health.get("service") != "gateway":
            raise RuntimeError("The server gateway is not available")
        mount = MountedFolder(config["WORKSPACE_ROOT"], mode,
                              f"http://127.0.0.1:{port}/", body["mount_token"], uid, gid)
        mount.start()
        sid = rpc("create", request_id=mount.workspace, workspace=mount.workspace, mode=mode)["session_id"]
        emit({"state": "ready", "session_id": sid, "workspace": mount.workspace})

        def control():
            # EOF means the owning SSH connection disappeared. No detached daemon.
            pending = b""
            try:
                while True:
                    # Raw FD reads avoid a daemon holding stdin's buffered lock
                    # during interpreter shutdown after SIGTERM/SIGHUP.
                    data = os.read(sys.stdin.fileno(), 1024)
                    if not data:
                        break
                    pending += data
                    if b"close\n" in pending or len(pending) > 4096:
                        break
            except OSError:
                pass
            stop.set()
        threading.Thread(target=control, daemon=True).start()
        while not stop.wait(1):
            mount.renew()
    except Exception as exc:
        failed = True
        # Never echo the control message or its credentials.
        emit({"state": "error", "message": str(exc) if isinstance(exc, (Fault, RuntimeError))
              else "Remote mount setup or transport failed; check server prerequisites"})
    finally:
        if mount:
            try:
                mount.revoke()
                if sid:
                    rpc("release", session_id=sid)
            except Exception:
                failed = True
                emit({"state": "error", "message": "Session release failed; lease expiry stops active operations"})
            try:
                mount.close()
            except Exception:
                failed = True
                emit({"state": "error", "message": "Unmount failed; inspect server mountpoints before retrying"})
        emit({"state": "closed"})
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
