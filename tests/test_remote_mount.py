import http.client
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock, patch

from client.remote import ssh_command
from client.workspace_server import WorkspaceServer, parts_for
from runtime.common import Fault
from runtime.mount_lease import check_lease, write_lease
from runtime.remote_mount import MountedFolder, emit, mount_command
from runtime.sandbox_manager import SandboxManager
from tests.support import FixtureProcessEngine


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "work"
        self.root.mkdir()
        self.export = WorkspaceServer(self.root)

    def tearDown(self):
        self.export.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, headers=None, token=True):
        conn = http.client.HTTPConnection("127.0.0.1", self.export.port, timeout=3)
        try:
            extra = {"Authorization": "Bearer " + self.export.token} if token else {}
            conn.request(method, path, body, {**extra, **(headers or {})})
            response = conn.getresponse()
            return response.status, response.read()
        finally:
            conn.close()

    def test_bidirectional_files_ranges_and_directory_listing(self):
        (self.root / "local.txt").write_text("from client")
        self.assertEqual(self.request("GET", "/local.txt"), (200, b"from client"))
        self.assertEqual(self.request("GET", "/local.txt", headers={"Range": "bytes=5-10"}), (206, b"client"))
        self.assertEqual(self.request("MKCOL", "/sub")[0], 201)
        self.assertEqual(self.request("PUT", "/sub/agent.txt", b"from agent")[0], 201)
        self.assertEqual((self.root / "sub/agent.txt").read_bytes(), b"from agent")
        status, body = self.request("PROPFIND", "/sub/", headers={"Depth": "1"})
        self.assertEqual(status, 207)
        self.assertEqual([e.text for e in ET.fromstring(body).iter("{DAV:}href")], ["/sub/", "/sub/agent.txt"])
        self.assertEqual(self.request("MOVE", "/sub/agent.txt", headers={"Destination": "/renamed.txt"})[0], 201)
        self.assertEqual(self.request("DELETE", "/renamed.txt")[0], 204)
        self.assertEqual(self.request("DELETE", "/sub")[0], 204)
        (self.root / "local.txt").write_text("client changed the file")
        self.assertEqual(self.request("GET", "/local.txt")[1], b"client changed the file")

    def test_authentication_readonly_and_protected_entries(self):
        self.assertEqual(self.request("GET", "/.agent-health", token=False)[0], 401)
        self.assertEqual(self.request("GET", "/.agent-health"), (200, b"workspace-v1"))
        (self.root / ".git").mkdir()
        (self.root / ".git/config").write_text("protected")
        (self.root / "nested").mkdir()
        (self.root / "nested/.git").write_text("gitdir: private")
        for path in ("/.git/config", "/nested/.git", "/../outside", "/%2e%2e/outside", "/.agent-upload-secret"):
            for method in ("GET", "PUT", "DELETE"):
                self.assertEqual(self.request(method, path, b"bad" if method == "PUT" else None)[0], 403)
        self.assertEqual(self.request("DELETE", "/nested")[0], 409)
        self.assertEqual(self.request("MOVE", "/nested", headers={"Destination": "/elsewhere"})[0], 403)
        self.assertNotIn(b".git", self.request("PROPFIND", "/", headers={"Depth": "1"})[1])
        self.export.mode = "ro"
        for method in ("PUT", "MKCOL", "DELETE", "MOVE"):
            self.assertEqual(self.request(method, "/new", b"bad" if method == "PUT" else None)[0], 403)
        self.assertFalse((self.root / "new").exists())

    def test_symlinks_hardlinks_and_special_files_are_not_exported(self):
        outside = Path(self.tmp.name) / "outside"
        outside.write_text("SECRET")
        (self.root / "link").symlink_to(outside)
        (self.root / "dirlink").symlink_to(outside.parent, target_is_directory=True)
        os.link(outside, self.root / "hardlink")
        os.mkfifo(self.root / "pipe")
        for path in ("/link", "/dirlink/outside", "/hardlink", "/pipe"):
            for method in ("GET", "PUT", "DELETE"):
                self.assertIn(self.request(method, path, b"bad" if method == "PUT" else None)[0], (403, 409))
        self.assertEqual(outside.read_text(), "SECRET")
        self.assertNotIn(b"link", self.request("PROPFIND", "/", headers={"Depth": "1"})[1])

    def test_interrupted_upload_does_not_truncate_original(self):
        (self.root / "file").write_text("original")
        conn = http.client.HTTPConnection("127.0.0.1", self.export.port, timeout=3)
        conn.putrequest("PUT", "/file")
        conn.putheader("Authorization", "Bearer " + self.export.token)
        conn.putheader("Content-Length", "100")
        conn.endheaders()
        conn.send(b"incomplete")
        conn.close()
        # Wait on the exporter lock: the request must finish before checking staging.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.request("GET", "/.agent-health")
            if not list(self.root.glob(".agent-upload-*")):
                break
        self.assertEqual((self.root / "file").read_text(), "original")
        self.assertEqual(list(self.root.glob(".agent-upload-*")), [])

    def test_simultaneous_local_edit_is_not_silently_overwritten_during_upload(self):
        target = self.root / "file"
        target.write_text("original")
        conn = http.client.HTTPConnection("127.0.0.1", self.export.port, timeout=3)
        try:
            conn.putrequest("PUT", "/file")
            conn.putheader("Authorization", "Bearer " + self.export.token)
            conn.putheader("Content-Length", "4")
            conn.endheaders()
            conn.send(b"ab")
            deadline = time.monotonic() + 2
            while not list(self.root.glob(".agent-upload-*")) and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(list(self.root.glob(".agent-upload-*")))
            target.write_text("local edit")
            conn.send(b"cd")
            response = conn.getresponse()
            self.assertEqual(response.status, 409)
            response.read()
        finally:
            conn.close()
        self.assertEqual(target.read_text(), "local edit")

    def test_chunked_upload_and_unicode_names(self):
        name = urllib.parse.quote("данные %.txt")
        conn = http.client.HTTPConnection("127.0.0.1", self.export.port, timeout=3)
        try:
            conn.request("PUT", "/" + name, iter([b"first", b"second"]),
                         {"Authorization": "Bearer " + self.export.token}, encode_chunked=True)
            response = conn.getresponse()
            self.assertEqual(response.status, 201)
            response.read()
        finally:
            conn.close()
        self.assertEqual((self.root / "данные %.txt").read_bytes(), b"firstsecond")

    def test_liveness_probe_does_not_wait_for_file_io(self):
        with self.export.lock:
            self.assertEqual(self.request("GET", "/.agent-health"), (200, b"workspace-v1"))

    def test_duplicate_export_rejected_without_lock_file(self):
        with self.assertRaises(BlockingIOError):
            WorkspaceServer(self.root)
        self.assertEqual(list(self.root.iterdir()), [])


class RemoteMountTests(unittest.TestCase):
    def test_ssh_command_quotes_paths_keeps_checks_and_loopback_binds(self):
        args = ssh_command("user@server", "/home/user/a folder/$(bad)", 22, 18080, 18081, 19001, 19002)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertIn("ExitOnForwardFailure=yes", args)
        self.assertIn("127.0.0.1:19002:127.0.0.1:19001", args)
        self.assertIn("127.0.0.1:18081:127.0.0.1:18080", args)
        self.assertIn("'/home/user/a folder/$(bad)'", args[-1])
        with self.assertRaises(ValueError):
            ssh_command("-oProxyCommand=bad", "/repo", 22, 18080, 18081, 19001, 19002)
        args = mount_command("/mount", "ro", 1000, 1000)
        self.assertIn("--read-only", args)
        self.assertEqual(args[args.index("--vfs-cache-mode") + 1], "off")

    def test_missing_lease_blocks_remote_workspace_and_expiry_stops_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = "remote-" + "a" * 32
            (root / workspace).mkdir()
            engine = FixtureProcessEngine()
            manager = SandboxManager(engine, root, root)
            try:
                with self.assertRaises(Fault):
                    manager.provision("s", workspace, "rw")
                write_lease(root, workspace, "rw", time.time() + 10)
                with self.assertRaises(Fault):
                    manager.provision("wrong-mode", workspace, "ro")
                manager.provision("s", workspace, "rw")
                results = []
                worker = threading.Thread(target=lambda: results.append(manager.exec(
                    "s", "op", "RunCommand", {"command": "sleep 10"}, 20)))
                worker.start()
                deadline = time.monotonic() + 3
                while not manager.session("s")["active"] and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertIsNotNone(manager.session("s")["active"])
                write_lease(root, workspace, "rw", 0)
                worker.join(timeout=3)
                self.assertFalse(worker.is_alive())
                self.assertEqual(results[0]["error"]["kind"], "transport")
                self.assertFalse(engine.containers)
                result = manager.exec("s", "next", "RunCommand", {"command": "echo bad"}, 2)
                self.assertEqual(result["error"]["kind"], "transport")
            finally:
                manager.close()
                engine.close()

    def test_cleanup_never_recursively_removes_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            mount = MountedFolder(tmp, "rw", "http://127.0.0.1:1/", "token", 1000, 1000)
            mount.path.mkdir()
            mount.created = True
            (mount.path / "unexpected.txt").write_text("keep")
            with self.assertRaises(OSError):
                mount.close()
            self.assertEqual((mount.path / "unexpected.txt").read_text(), "keep")


class HelperCleanupTests(unittest.TestCase):
    def test_broken_ssh_stdout_does_not_interrupt_cleanup(self):
        with patch("builtins.print", side_effect=BrokenPipeError):
            emit({"state": "error", "message": "disconnected"})
            emit({"state": "closed"})

    def test_failed_lease_revoke_still_stops_mount_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            mount = MountedFolder(tmp, "rw", "http://127.0.0.1:1/", "token", 1000, 1000)
            mount.path.mkdir()
            mount.created = True
            mount.process = Mock()
            mount.process.poll.return_value = None
            with patch.object(mount, "revoke", side_effect=OSError("read-only metadata")):
                with self.assertRaises(OSError):
                    mount.close()
            mount.process.terminate.assert_called_once()
            mount.process.wait.assert_called_once()

    def test_failed_ssh_start_releases_local_export(self):
        from client.remote import RemoteClient
        with tempfile.TemporaryDirectory() as tmp:
            remote = RemoteClient("client-token", "server", "/repo")
            with patch("client.remote.subprocess.Popen", side_effect=FileNotFoundError("ssh")):
                with self.assertRaises(FileNotFoundError):
                    remote.create(tmp)
            self.assertIsNone(remote.export)
            # The directory lock and listener have been released.
            again = WorkspaceServer(tmp)
            again.close()


class RemoteClientLifecycleTests(unittest.TestCase):
    def test_real_control_process_is_reaped_and_export_released(self):
        import subprocess
        import sys
        from client.remote import RemoteClient
        original = subprocess.Popen
        processes = []
        helper = (
            "import json,sys; body=json.loads(sys.stdin.readline()); "
            "assert len(body['mount_token']) >= 32; "
            "print(json.dumps({'state':'ready','session_id':'s','workspace':'remote-'+'a'*32}),flush=True); "
            "assert sys.stdin.readline().strip()=='close'; "
            "print(json.dumps({'state':'closed'}),flush=True)"
        )

        def start(command, **kwargs):
            self.assertNotIn("client-secret", " ".join(command))
            process = original([sys.executable, "-u", "-c", helper], **kwargs)
            processes.append(process)
            return process

        with tempfile.TemporaryDirectory() as tmp:
            remote = RemoteClient("client-secret", "server", "/repo")
            with patch("client.remote.subprocess.Popen", side_effect=start):
                try:
                    self.assertEqual(remote.create(tmp), "s")
                    remote.ensure_connected()
                finally:
                    remote.close()
            self.assertEqual(processes[0].returncode, 0)
            self.assertIsNone(remote.last_error)
            self.assertIsNone(remote.export)
            again = WorkspaceServer(tmp)
            again.close()
