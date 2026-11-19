"""CI-only loopback SSH + FUSE + Docker integration; requires passwordless sudo.

Uses disposable keys/configs and loopback ports, not the machine's SSH service.
For a real two-machine demo run scripts.check_remote on the client instead.
"""
import argparse
import getpass
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from client.remote import free_port


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-port", type=int, default=18080)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix=".project-a-ssh-", dir=Path.home()) as tmp:
        folder = Path(tmp)
        for name in ("host", "client"):
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(folder / name)], check=True)
        (folder / "authorized_keys").write_text((folder / "client.pub").read_text())
        (folder / "authorized_keys").chmod(0o600)
        port = free_port()
        (folder / "known_hosts").write_text(f"[127.0.0.1]:{port} " + (folder / "host.pub").read_text())
        (folder / "client.conf").write_text(
            f"Host project-a-mount-ci\n  HostName 127.0.0.1\n  User {getpass.getuser()}\n"
            f"  IdentityFile {folder}/client\n  IdentitiesOnly yes\n  UserKnownHostsFile {folder}/known_hosts\n")
        config = folder / "sshd.conf"
        config.write_text(f"Port {port}\nListenAddress 127.0.0.1\nHostKey {folder}/host\n"
                          f"PidFile {folder}/sshd.pid\nAuthorizedKeysFile {folder}/authorized_keys\n"
                          "PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n"
                          "UsePAM yes\nAllowTcpForwarding yes\nGatewayPorts no\nLogLevel ERROR\n")
        process = subprocess.Popen(["sudo", "-n", "/usr/sbin/sshd", "-D", "-e", "-f", str(config)])
        try:
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Ephemeral sshd failed")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Ephemeral sshd did not start")
                    time.sleep(0.1)
            subprocess.run([sys.executable, "-B", "-m", "scripts.check_remote", "--ssh-host", "project-a-mount-ci",
                            "--server-repo", str(Path.cwd()), "--ssh-port", str(port),
                            "--ssh-config", str(folder / "client.conf"), "--gateway-port", str(args.gateway_port)], check=True)
        finally:
            if (folder / "sshd.pid").exists():
                pid = int((folder / "sshd.pid").read_text())
                subprocess.run(["sudo", "-n", "kill", str(pid)], check=False)
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
