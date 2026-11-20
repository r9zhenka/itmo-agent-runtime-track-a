"""One-command offline acceptance in a disposable replay stack.

Preparation (OS packages, cached images, pinned rclone) is deliberately separate.
No live-model configuration or user workspace is copied into this temporary stack.
"""
import argparse
import contextlib
import fcntl
import getpass
import json
import os
import secrets
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from scripts.measure_common import environment, save_report


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def copy_source(source, target):
    for name in ("runtime", "client", "baf", "scripts", "tests", "contracts"):
        shutil.copytree(source / name, target / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in ("Dockerfile", "sandbox.Dockerfile", "docker-compose.yml", ".env.example"):
        shutil.copy2(source / name, target / name)


    # Fixed, public benchmark evidence only; never copy arbitrary docs or .env.
    evidence = source / "docs/evidence/cp2-fixes"
    for name in ("provider-record-smoke.jsonl", "provider-record-events.json"):
        if (evidence / name).is_file():
            destination = target / "recording-evidence"
            destination.mkdir(exist_ok=True)
            shutil.copyfile(evidence / name, destination / name)


def replay_environment(root, port, project):
    env = dict(os.environ)
    for key in list(env):
        if key.startswith(("LLM_", "COMPOSE_")) or key == "PYTHONPATH":
            env.pop(key)
    env.update(LLM_MODE="replay", LLM_API_KEY="", LLM_PROVIDER_URL="", LLM_MODEL="",
               LLM_EXTRA_JSON="{}", LLM_HTTP_PROXY="", LLM_PROXY_SOCKET="",
               ALLOW_LOCAL_RW="1", GATEWAY_PORT=str(port), GATEWAY_BIND="127.0.0.1",
               WORKSPACE_ROOT=str(root / "workspaces"), INSTANCE_ID=project,
               CLIENT_TOKEN=secrets.token_urlsafe(32), INTERNAL_TOKEN=secrets.token_urlsafe(32),
               CLIENT_IDENTITIES_JSON="",
               SANDBOX_UID=str(os.getuid()), SANDBOX_GID=str(os.getgid()),
               PYTHONDONTWRITEBYTECODE="1")
    return env


@contextlib.contextmanager
def existing_sshd_key(port=22):
    """Authorize a temporary localhost-only key on our own account, then remove it.

    This avoids passwordless sudo on a development VM with an existing SSH server.
    Host identity is verified against its readable system public-key files.
    """
    home = Path.home()
    ssh_dir = home / ".ssh"
    ssh_dir.mkdir(mode=0o700, exist_ok=True)
    authorized = ssh_dir / "authorized_keys"
    marker = "project-a-check-" + uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix=".project-a-check-key-", dir=home) as tmp:
        folder = Path(tmp)
        key = folder / "key"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", marker, "-f", str(key)], check=True)
        scanned = subprocess.run(["ssh-keyscan", "-T", "3", "-p", str(port), "127.0.0.1"],
                                 capture_output=True, text=True, timeout=15)
        trusted = set()
        for path in Path("/etc/ssh").glob("ssh_host_*_key.pub"):
            fields = path.read_text().split()
            if len(fields) >= 2:
                trusted.add(tuple(fields[:2]))
        hosts = [line for line in scanned.stdout.splitlines()
                 if len(line.split()) >= 3 and tuple(line.split()[1:3]) in trusted]
        if not hosts:
            raise RuntimeError("Cannot verify the local sshd against /etc/ssh host public keys")
        (folder / "known_hosts").write_text("\n".join(hosts) + "\n")
        config = folder / "config"
        config.write_text(f"Host project-a-check-local\n  HostName 127.0.0.1\n  User {getpass.getuser()}\n"
                          f"  Port {port}\n  IdentityFile {key}\n  IdentitiesOnly yes\n"
                          f"  UserKnownHostsFile {folder}/known_hosts\n  StrictHostKeyChecking yes\n")
        entry = 'from="127.0.0.1",no-agent-forwarding,no-X11-forwarding,no-pty ' + key.with_suffix(".pub").read_text().strip()
        fd = os.open(authorized, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "r+", closefd=False) as file:
                fcntl.flock(fd, fcntl.LOCK_EX)
                contents = file.read()
                file.seek(0, os.SEEK_END)
                file.write(("\n" if contents and not contents.endswith("\n") else "") + entry + "\n")
                file.flush()
                fcntl.flock(fd, fcntl.LOCK_UN)
            try:
                yield config
            finally:
                # Preserve any concurrently added unrelated keys; remove only our exact line.
                with os.fdopen(fd, "r+", closefd=False) as file:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    file.seek(0)
                    contents = file.read()
                    file.seek(0)
                    file.write("\n".join(line for line in contents.splitlines() if line != entry) + "\n")
                    file.truncate()
                    file.flush()
                    fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def commands(python, rclone):
    return [
        ("offline-unit-cli-http", [python, "-m", "scripts.validate"]),
        ("docker-isolation", [python, "-m", "scripts.docker_check"]),
        ("isolated-code-grader", [python, "-m", "scripts.check_b6"]),
        ("adversarial-hardening", [python, "-m", "scripts.hardening_check"]),
        ("full-synthetic-baf", [python, "-m", "scripts.benchmark", "--repeats", "1", "--parallel", "3", "--pair", "custom+replay"]),
        ("real-webdav", [python, "-m", "scripts.check_webdav", "--rclone", rclone]),
        ("mount-helper-sigkill", [python, "-m", "scripts.check_mount_crash"]),
    ]


def verify_replay_results(path, expected_ids):
    records = [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]
    actual = [item.get("task") for item in records]
    if sorted(actual) != sorted(expected_ids):
        raise RuntimeError("Replay benchmark did not cover exactly the registered tasks once")
    for item in records:
        if not item.get("pass") or item.get("model", {}).get("provider") != "synthetic-replay" or item.get("quality_evaluation"):
            raise RuntimeError("Acceptance requires passing replay results, never live-model calls")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rclone", default=str(Path.home() / ".local/bin/rclone"))
    parser.add_argument("--existing-sshd", action="store_true",
                        help="Use own account on existing localhost sshd, with a temporary key; avoids sudo")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--output", default="results/check-all")
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error("Run as non-root with Docker access")
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "environment": environment(), "model": "synthetic-replay",
              "network": "Loopback/SSH and Docker bridges only; all images and tools must be prepared beforehand",
              "steps": []}
    rclone = str(Path(args.rclone).resolve())
    if not Path(rclone).is_file() or not Path("/dev/fuse").exists():
        parser.error("Prepare pinned rclone and /dev/fuse first; see docs/performance.md")
    subprocess.run(["docker", "image", "inspect", "project-a-service:cp1", "project-a-sandbox:cp1"],
                   check=True, stdout=subprocess.DEVNULL)
    project = "project-a-check-" + uuid.uuid4().hex[:12]
    with tempfile.TemporaryDirectory(prefix=".project-a-check-", dir=Path.home()) as tmp:
        checkout = Path(tmp)
        copy_source(root, checkout)
        (checkout / ".acceptance-stack.json").write_text(json.dumps({"project": project, "instance": project}))
        port = free_port()
        env = replay_environment(checkout, port, project)
        subprocess.run([sys.executable, "-m", "scripts.init"], cwd=checkout, env=env, check=True)
        # The SSH helper reads this file, not the invoking shell's environment.
        with (checkout / ".env").open("a") as file:
            for key in ("LLM_MODE", "LLM_API_KEY", "LLM_PROVIDER_URL", "LLM_MODEL", "LLM_EXTRA_JSON", "LLM_HTTP_PROXY",
                        "ALLOW_LOCAL_RW", "GATEWAY_PORT", "WORKSPACE_ROOT", "INSTANCE_ID", "CLIENT_TOKEN", "INTERNAL_TOKEN"):
                file.write(f"\n{key}='{env[key]}'")
            file.write("\n")
        compose = ["docker", "compose", "--project-name", project, "--file", str(checkout / "docker-compose.yml")]

        def run(name, command):
            print("CHECK: " + name, flush=True)
            started = time.monotonic()
            result = subprocess.run(command, cwd=checkout, env=env)
            report["steps"].append({"name": name, "passed": result.returncode == 0,
                                    "duration_seconds": round(time.monotonic() - started, 3)})
            if result.returncode:
                raise RuntimeError(name + " failed")

        try:
            run("start-isolated-replay-stack", compose + ["up", "--no-build", "--pull", "never", "-d", "--wait"])
            # Query the actual service rather than trusting only intended environment.
            probe = subprocess.run(compose + ["exec", "-T", "llm-proxy", "python", "-c",
                "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))['mode'])"],
                cwd=checkout, env=env, capture_output=True, text=True, check=True)
            if probe.stdout.strip() != "replay":
                raise RuntimeError("Refusing to test a live-model stack")
            for name, command in commands(sys.executable, rclone):
                run(name, command)
            from baf.cases import cases
            verify_replay_results(checkout / "results/baf.jsonl", [case["id"] for case in cases()])
            if args.existing_sshd:
                with existing_sshd_key(args.ssh_port) as config:
                    run("ssh-fuse-docker", [sys.executable, "-m", "scripts.check_remote",
                        "--ssh-host", "project-a-check-local", "--server-repo", str(checkout),
                        "--ssh-config", str(config), "--ssh-port", str(args.ssh_port), "--gateway-port", str(port)])
            else:
                # check_ssh_mount now takes its gateway port from this stack's environment.
                run("ssh-fuse-docker", [sys.executable, "-m", "scripts.check_ssh_mount", "--gateway-port", str(port)])
            run("deployed-controller-crashes", [sys.executable, "-m", "scripts.check_watchdog_crash", "--project", project])
            run("recording-artifact-audit", [sys.executable, "-m", "scripts.check_recordings",
                "--directory", "baf/recordings", "--output", "results/recorded-audit.json"])
            run("recording-context-audit", [sys.executable, "-m", "scripts.derive_recorded_contexts",
                "--directory", "baf/recordings", "--captures", "recording-evidence/provider-record-smoke.jsonl",
                "--events", "recording-evidence/provider-record-events.json", "--check"])
            env["LLM_MODE"] = "recorded"
            run("start-recorded-proxy", compose + ["up", "--no-build", "--pull", "never", "-d", "--wait",
                "--no-deps", "--force-recreate", "llm-proxy"])
            run("recorded-model-smoke", [sys.executable, "-m", "scripts.benchmark", "--smoke", "--repeats", "1", "--parallel", "3",
                "--pair", "custom+recorded-smoke", "--output", "results/recorded-smoke.jsonl"])
            recorded = [json.loads(line) for line in (checkout / "results/recorded-smoke.jsonl").read_text().splitlines()]
            expected = {case["id"] for case in cases() if case["id"].endswith(".1")}
            if (len(recorded) != len(expected) or {row.get("task") for row in recorded} != expected
                    or any(not row.get("pass") or row.get("model", {}).get("provider") != "recorded-replay"
                           or row.get("quality_evaluation") for row in recorded)):
                raise RuntimeError("Recorded smoke coverage or provenance failed")
            report["passed"] = True
        except Exception as exc:
            report["error"] = str(exc)
        finally:
            with (output / "compose.log").open("w") as log:
                subprocess.run(compose + ["logs", "--no-color"], cwd=checkout, env=env, stdout=log, stderr=subprocess.STDOUT)
            cleanup = subprocess.run(compose + ["down", "-v", "--remove-orphans"], cwd=checkout, env=env)
            report["cleanup_passed"] = cleanup.returncode == 0
            try:
                from runtime.docker_engine import Docker
                Docker().cleanup(project)  # Only this temporary stack's sandbox labels.
            except Exception as exc:
                report["cleanup_passed"] = False
                report["cleanup_error"] = str(exc)
            report["passed"] &= report["cleanup_passed"]
            results = checkout / "results"
            if results.exists():
                shutil.copytree(results, output / "artifacts", dirs_exist_ok=True)
            save_report(output / "summary.json", report)
    print("Full acceptance " + ("PASSED" if report["passed"] else "FAILED") + ": " + str(output / "summary.json"))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
