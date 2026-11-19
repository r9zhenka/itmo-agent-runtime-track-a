"""Own a local WebDAV export, two SSH forwards, and one remote agent session."""
import json
import queue
import re
import secrets
import shlex
import socket
import subprocess
import threading

from runtime.common import Fault
from .api import Client
from .workspace_server import WorkspaceServer


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def ssh_command(host, repo, ssh_port, gateway_port, local_port, export_port, reverse_port, ssh_config=None):
    if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.@-]*", host):
        raise ValueError("Use an SSH config alias or user@hostname")
    if not repo.startswith("/") or any(c in repo for c in "\n\r\x00"):
        raise ValueError("Server repository path must be absolute")
    for port in (ssh_port, gateway_port, local_port, export_port, reverse_port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("Invalid TCP port")
    return ["ssh", *(["-F", str(ssh_config)] if ssh_config else []), "-T", "-p", str(ssh_port),
            "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ExitOnForwardFailure=yes", "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=3",
            "-o", "ControlMaster=no", "-o", "ControlPath=none",
            "-L", f"127.0.0.1:{local_port}:127.0.0.1:{gateway_port}",
            "-R", f"127.0.0.1:{reverse_port}:127.0.0.1:{export_port}",
            host, "cd -- " + shlex.quote(repo) + " && exec python3 -u -m runtime.remote_mount"]


class RemoteClient(Client):
    def __init__(self, token, ssh_host, server_repo, ssh_port=22, gateway_port=18080, ssh_config=None):
        super().__init__("http://127.0.0.1:1", token)
        self.ssh_host, self.server_repo = ssh_host, server_repo
        self.ssh_port, self.gateway_port = ssh_port, gateway_port
        self.ssh_config = ssh_config
        self.export = self.process = self.session_id = None
        self.events = queue.Queue()
        self.last_error = None
        self.stderr_tail = None
        self.readers = []

    def create(self, workspace, mode="rw", request_id=None):
        if self.process is not None:
            raise Fault("busy", "Release the previous remote folder first", 409)
        self.events = queue.Queue()
        self.last_error = self.stderr_tail = None
        try:
            self.export = WorkspaceServer(workspace, mode)
            local_port, reverse_port = free_port(), 20000 + secrets.randbelow(40000)
            command = ssh_command(self.ssh_host, self.server_repo, self.ssh_port, self.gateway_port,
                                  local_port, self.export.port, reverse_port, self.ssh_config)
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                            stderr=subprocess.PIPE, text=True, bufsize=1)

            def stdout():
                try:
                    for line in self.process.stdout:
                        try:
                            event = json.loads(line)
                        except ValueError:
                            event = {"state": "error", "message": "Invalid SSH helper response"}
                        if event.get("state") == "error":
                            self.last_error = event.get("message", "Remote mount failed")
                        self.events.put(event)
                finally:
                    self.events.put({"state": "closed"})

            def stderr():
                for line in self.process.stderr:
                    # Keep a bounded final diagnostic, never print credentials.
                    self.stderr_tail = line.strip()[:1000]

            self.readers = [threading.Thread(target=fn, daemon=True) for fn in (stdout, stderr)]
            for thread in self.readers:
                thread.start()
            self.process.stdin.write(json.dumps({"port": reverse_port, "mode": mode,
                "mount_token": self.export.token, "client_token": self.token}) + "\n")
            self.process.stdin.flush()
            event = self.events.get(timeout=35)
            if event.get("state") != "ready":
                raise Fault("transport", self.last_error or self.stderr_tail or event.get("message", "SSH mount helper exited"), 503)
            self.session_id = event["session_id"]
            self.workspace = event["workspace"]
            Client.__init__(self, f"http://127.0.0.1:{local_port}", self.token)
            return self.session_id
        except queue.Empty:
            self.close()
            raise Fault("timeout", "Timed out establishing the SSH mount; check server prerequisites", 504) from None
        except BaseException:
            self.close()
            raise

    def ensure_connected(self):
        if self.process is None or self.process.poll() is not None:
            raise Fault("transport", self.last_error or self.stderr_tail or "Client folder disconnected; reconnect it", 503)

    def send(self, *args, **kwargs):
        self.ensure_connected()
        return super().send(*args, **kwargs)

    def release(self, session_id):
        try:
            return super().release(session_id)
        finally:
            self.close()
            if self.last_error:
                raise Fault("transport", self.last_error, 503)

    def close(self):
        error = None
        if self.process is not None:
            process = self.process
            try:
                if process.poll() is None:
                    try:
                        process.stdin.write("close\n")
                        process.stdin.flush()
                        process.stdin.close()
                    except (OSError, ValueError):
                        pass
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                    error = "Remote cleanup timed out; inspect the server mountpoint"
                if process.returncode:
                    error = self.last_error or self.stderr_tail or "Remote mount helper exited with an error"
            finally:
                for thread in self.readers:
                    thread.join(timeout=2)
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
                self.process = None
        if self.export is not None:
            self.export.close()
            self.export = None
        if error:
            self.last_error = error
