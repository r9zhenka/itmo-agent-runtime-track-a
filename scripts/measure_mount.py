"""Measure local versus remotely mounted filesystem performance; no model calls."""
import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from client.api import settings
from client.remote import RemoteClient, ssh_command
from scripts.measure_common import environment, save_report
from scripts.measure_mount_worker import measure, payload, prepare_fixture


def remote_command(args, workspace):
    base = ssh_command(args.ssh_host, args.server_repo, args.ssh_port,
                       args.gateway_port, 18081, 19001, 19002, args.ssh_config)
    words = ["python3", "-m", "scripts.measure_mount_worker", "--workspace", workspace,
             "--repeats", str(args.repeats)]
    return base[:base.index("-L")] + [args.ssh_host,
        "cd -- " + shlex.quote(args.server_repo) + " && " + shlex.join(words)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--server-repo", required=True)
    parser.add_argument("--ssh-config")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--gateway-port", type=int, default=18080)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--output", default="results/mount-performance.json")
    args = parser.parse_args()
    if not 10 <= args.repeats <= 100:
        parser.error("Use 10..100 repeats")
    token = os.getenv("CLIENT_TOKEN", settings().get("CLIENT_TOKEN", ""))
    if not token:
        parser.error("Set CLIENT_TOKEN for the remote server")
    report = {"passed": False, "client_environment": environment(), "repeats": args.repeats,
              "model_calls": 0, "method": "Repeated warm-cache operations, no cache dropping; nearest-rank p95"}
    try:
        with tempfile.TemporaryDirectory(prefix="project-a-mount-measurement-") as tmp:
            root = Path(tmp) / "fixture"
            config = prepare_fixture(root)
            report["local_baseline"] = measure(root, args.repeats)
            # The local baseline ends with the same marker sequence as the remote
            # worker. Reset it so the final client check proves a new remote write.
            (root / "write.bin").write_bytes(payload(config["write_bytes"], 67))
            remote = RemoteClient(token, args.ssh_host, args.server_repo, args.ssh_port,
                                  args.gateway_port, args.ssh_config)
            try:
                sid = remote.create(str(root), "rw")
                run = subprocess.run(remote_command(args, remote.workspace), capture_output=True,
                                     text=True, timeout=max(180, args.repeats * 20))
                if run.returncode:
                    # Worker has no API credentials or user data; output is fixture-only.
                    raise RuntimeError("Remote measurement failed: " + run.stderr[-2000:])
                report["mounted"] = json.loads(run.stdout)
                if len(report["mounted"]["raw"]) != args.repeats or not report["mounted"].get("is_mount"):
                    raise RuntimeError("Remote worker returned incomplete or non-mount evidence")
                if (root / "write.bin").read_bytes() != payload(config["write_bytes"], 68 + (args.repeats - 1) % 20):
                    raise AssertionError("Server writes were not visible on the client")
                report["client_observed_write"] = True
                remote.release(sid)
                if remote.last_error:
                    raise RuntimeError("Remote cleanup failed")
                report["cleanup_completed"] = True
            finally:
                remote.close()
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        save_report(args.output, report)
    print("Mount measurements saved to " + args.output)
    for metric, values in report["mounted"]["summary"].items():
        print(f"{metric}: median={values['median']:.3f}, p95={values['p95']:.3f}, n={values['n']}")


if __name__ == "__main__":
    main()
