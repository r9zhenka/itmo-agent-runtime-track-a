"""Real rclone/FUSE test: kill only a disposable helper, then inspect guard cleanup.

Run on the configured Linux mount host as its non-root user. No Docker, LLM,
existing session or user workspace is touched. Requires pinned rclone and FUSE.
"""
import argparse
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from client.workspace_server import WorkspaceServer
from runtime.mount_lease import CONTROL
from runtime.remote_mount import GuardedMount, check_dependencies


def worker():
    config = json.loads(sys.stdin.readline(16384))
    mount = GuardedMount(**config)
    try:
        mount.start()
        print(json.dumps({"workspace": mount.workspace, "guard_pid": mount.process.pid}), flush=True)
        sys.stdin.read()
    finally:
        mount.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--output", default="results/mount-crash.json")
    args = parser.parse_args()
    if args.worker:
        worker()
        return 0
    check_dependencies()
    if os.getuid() == 0:
        raise RuntimeError("Run this mount check as the ordinary non-root server user")
    checks = []
    process = export = None
    guard_pidfd = None
    completed = False
    with tempfile.TemporaryDirectory(prefix="project-a-mount-crash-") as tmp:
        base = Path(tmp)
        source, root = base / "client", base / "mounts"
        source.mkdir()
        root.mkdir()
        (source / "original.txt").write_text("keep original")
        try:
            export = WorkspaceServer(source)
            process = subprocess.Popen([sys.executable, "-u", "-m", "scripts.check_mount_crash", "--worker"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            config = {"root": str(root), "mode": "rw", "url": f"http://127.0.0.1:{export.port}/",
                      "token": export.token, "uid": os.getuid(), "gid": os.getgid()}
            process.stdin.write(json.dumps(config) + "\n")
            process.stdin.flush()
            if not select.select([process.stdout], [], [], 40)[0]:
                raise AssertionError("Mount helper did not become ready")
            ready = json.loads(process.stdout.readline())
            guard_pidfd = os.pidfd_open(ready["guard_pid"])
            mountpoint = root / ready["workspace"]
            lease = root / CONTROL / (ready["workspace"] + ".json")
            assert os.path.ismount(mountpoint) and lease.is_file()
            assert (mountpoint / "original.txt").read_text() == "keep original"
            (mountpoint / "agent.txt").write_text("guarded write")
            assert (source / "agent.txt").read_text() == "guarded write"
            checks.append({"check": "real FUSE mount reads and writes", "passed": True})
            process.kill()
            process.wait(timeout=5)
            deadline = time.monotonic() + 35
            while time.monotonic() < deadline and (os.path.ismount(mountpoint) or mountpoint.exists() or lease.exists()):
                time.sleep(0.1)
            clean = not os.path.ismount(mountpoint) and not mountpoint.exists() and not lease.exists()
            checks.append({"check": "helper SIGKILL removes FUSE mountpoint and lease", "passed": clean})
            assert clean, "Guard did not finish cleanup"
            intact = ((source / "original.txt").read_text() == "keep original"
                      and (source / "agent.txt").read_text() == "guarded write")
            checks.append({"check": "original and agent-written client files survive", "passed": intact})
            assert intact
            completed = True
        finally:
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=40)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                process.stdin.close()
                process.stdout.close()
            if not completed and guard_pidfd is not None:
                # Only our freshly created guard. SIGTERM requests its normal
                # cleanup; never recursively remove a still-mounted directory.
                try:
                    signal.pidfd_send_signal(guard_pidfd, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 35
                while mountpoint.exists() and time.monotonic() < deadline:
                    time.sleep(0.1)
            if export is not None:
                export.close()
            if guard_pidfd is not None:
                os.close(guard_pidfd)
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps({"backend": "real rclone/FUSE + independent mount guard",
                                          "passed": completed, "checks": checks}, indent=2) + "\n")
            # TemporaryDirectory's recursive cleanup must never cross FUSE.
            if any(os.path.ismount(path) for path in root.iterdir()):
                base.rename(base.with_name(base.name + "-needs-cleanup"))
                raise RuntimeError("A test mount remains; temporary tree preserved for manual cleanup")
    for item in checks:
        print("PASS: " + item["check"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
