"""Own one FUSE mount until the controlling SSH helper's pipe closes.

Runs outside Compose with the ordinary SSH user's privileges. No Docker socket
or client RPC token is needed. A separate session survives helper SIGKILL/SIGHUP;
all rclone children close the control descriptors, so helper death yields EOF.
"""
import json
import queue
import signal
import sys
import threading

from .remote_mount import MountedFolder, emit


def supervise(config, control, publish, stop, mount_factory=MountedFolder):
    mount = mount_factory(**config)
    failed = False
    try:
        mount.start()
        publish({"state": "ready", "workspace": mount.workspace})
        revoked = False
        while not stop.is_set():
            try:
                command = control.get(timeout=1)
            except queue.Empty:
                if not revoked:
                    mount.renew()
                continue
            if command == "close":
                break
            if command == "revoke":
                mount.revoke()
                revoked = True
                publish({"state": "revoked"})
            else:
                raise ValueError("Invalid mount guard command")
    except Exception:
        failed = True
        publish({"state": "error", "message": "Mount guard failed"})
    finally:
        try:
            mount.close()
        except Exception:
            failed = True
            publish({"state": "error", "message": "Mount cleanup failed"})
        publish({"state": "closed"})
    return int(failed)


def main():
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: stop.set())
    config = json.loads(sys.stdin.readline(16384))
    commands = queue.Queue()

    def read_control():
        # Avoid leaving a buffered-stdin lock held by a daemon at shutdown.
        import os
        pending = b""
        try:
            while True:
                data = os.read(sys.stdin.fileno(), 1024)
                if not data:
                    break
                pending += data
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    commands.put(line.decode("ascii"))
                if len(pending) > 1024:
                    break
        finally:
            commands.put("close")

    threading.Thread(target=read_control, daemon=True).start()
    return supervise(config, commands, emit, stop)


if __name__ == "__main__":
    raise SystemExit(main())
