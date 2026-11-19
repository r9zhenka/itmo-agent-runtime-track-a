"""Acceptance test using a real SSH host, FUSE, Compose and Docker sandbox.

Use a disposable test server in LLM_MODE=replay. This does not evaluate a model.
The only client files changed are in this script's TemporaryDirectory.
"""
import argparse
import json
import os
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from baf.cases import cases, prepare, prompt
from client.api import settings
from client.remote import RemoteClient, ssh_command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--server-repo", required=True)
    parser.add_argument("--ssh-config")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--gateway-port", type=int, default=18080)
    args = parser.parse_args()
    token = os.getenv("CLIENT_TOKEN", settings().get("CLIENT_TOKEN", ""))
    records = []

    def record(name, condition):
        records.append({"check": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)
        print("PASS: " + name, flush=True)

    def client():
        return RemoteClient(token, args.ssh_host, args.server_repo, args.ssh_port, args.gateway_port, args.ssh_config)

    def run(remote, sid, case):
        run_id = remote.send(sid, prompt(case))
        events = list(remote.watch(sid, run_id))
        record("replay provider used", any(e.get("provider") == "synthetic-replay" for e in events))
        return events[-1]

    def clean(workspace, timeout=25):
        # Separate SSH connection proves cleanup even after the owning tunnel dies.
        base = ssh_command(args.ssh_host, args.server_repo, args.ssh_port,
                           args.gateway_port, 18081, 19001, 19002, args.ssh_config)
        command = base[:base.index("-L")] + [args.ssh_host,
            "cd -- " + shlex.quote(args.server_repo) + " && python3 -m scripts.inspect_remote " + shlex.quote(workspace)]
        deadline = time.monotonic() + timeout
        while True:
            result = subprocess.run(command, capture_output=True, text=True, timeout=15, check=True)
            state = json.loads(result.stdout)
            if not any(state.values()):
                return True
            if time.monotonic() >= deadline:
                print(json.dumps(state))
                return False
            time.sleep(1)

    try:
        with tempfile.TemporaryDirectory(prefix="project-a-two-machines-") as tmp:
            folder = Path(tmp) / "workspace"
            case = next(c for c in cases() if c["id"] == "B2.1")
            prepare(case, folder)
            remote = client()
            try:
                sid = remote.create(str(folder), "rw")
                result = run(remote, sid, case)
                record("sandbox reads client files and writes back", result["outcome"] == "success"
                       and (folder / "answer.txt").read_text().strip() == "src/dates.py")
                (folder / "src/dates.py").rename(folder / "src/new_dates.py")
                result = run(remote, sid, case)
                record("client edits visible to next sandbox command", result["outcome"] == "success"
                       and (folder / "answer.txt").read_text().strip() == "src/new_dates.py")
                remote.release(sid)
                record("clean remote release", remote.last_error is None and clean(remote.workspace))
            finally:
                remote.close()
            (folder / "answer.txt").unlink()
            remote = client()
            try:
                sid = remote.create(str(folder), "ro")
                run(remote, sid, case)
                record("read-only rejects sandbox writes", not (folder / "answer.txt").exists())
                remote.release(sid)
            finally:
                remote.close()
            remote = client()
            try:
                remote.create(str(folder), "rw")
                # Lose the owning SSH connection, rather than requesting release.
                remote.process.kill()
                remote.process.wait(timeout=5)
                remote.export.close()
                remote.export = None
                record("disconnect removes mount, lease and containers", clean(remote.workspace))
            finally:
                remote.close()
            record("client originals survive sessions", (folder / "src/new_dates.py").is_file())
        print("Remote mount acceptance completed, including server-side cleanup inspection.")
    finally:
        output = Path("results/remote-mount.json")
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps({"backend": "SSH + WebDAV + rclone FUSE + Docker",
                                      "checks": records}, indent=2) + "\n")


if __name__ == "__main__":
    main()
