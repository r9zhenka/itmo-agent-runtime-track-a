import http.client
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from client.workspace_server import WorkspaceServer
from runtime.mount_guard import supervise


class ExportLockTests(unittest.TestCase):
    def test_parent_child_conflicts_in_both_directions_but_siblings_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a").mkdir()
            (root / "b").mkdir()
            for first, second in ((root, root / "a"), (root / "a", root)):
                server = WorkspaceServer(first)
                try:
                    with self.assertRaises(BlockingIOError):
                        WorkspaceServer(second)
                finally:
                    server.close()
            a, b = WorkspaceServer(root / "a"), WorkspaceServer(root / "b")
            a.close()
            b.close()

    def test_cross_process_overlap_rejected_and_sigkill_releases_registry_locks(self):
        with tempfile.TemporaryDirectory() as tmp:
            child = Path(tmp) / "child"
            child.mkdir()
            code = ("import sys; from client.workspace_server import WorkspaceServer; "
                    "s=WorkspaceServer(sys.argv[1]); print('ready',flush=True); sys.stdin.read(); s.close()")
            process = subprocess.Popen([sys.executable, "-c", code, str(child)],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), "ready")
                with self.assertRaises(BlockingIOError):
                    WorkspaceServer(tmp)
                process.kill()
                process.wait(timeout=3)
                server = WorkspaceServer(tmp)
                server.close()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
                process.stdin.close()
                process.stdout.close()


class MutationConflictTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.server = WorkspaceServer(self.root)
        (self.root / "source").write_text("original")

    def tearDown(self):
        self.server.close()
        self.temp.cleanup()

    def request(self, method, path="/source", body=None, **headers):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=3)
        try:
            conn.request(method, path, body, {"Authorization": "Bearer " + self.server.token, **headers})
            response = conn.getresponse()
            response.read()
            return response.status, dict(response.getheaders())
        finally:
            conn.close()

    def test_conditional_put_move_delete_reject_stale_etag(self):
        _, headers = self.request("HEAD")
        version = headers["ETag"]
        (self.root / "source").write_text("new local edit")
        for method in ("PUT", "MOVE", "DELETE"):
            with self.subTest(method=method):
                status, _ = self.request(method, body=b"replacement" if method == "PUT" else None,
                                         **{"If-Match": version, "Destination": "/dest"})
                self.assertEqual(status, 412)
                self.assertEqual((self.root / "source").read_text(), "new local edit")
        status, _ = self.request("PUT", body=b"new", **{"If-None-Match": "*"})
        self.assertEqual(status, 412)

    def test_conditional_operations_succeed_with_current_etag(self):
        for method in ("PUT", "MOVE", "DELETE"):
            _, headers = self.request("HEAD")
            status, _ = self.request(method, body=b"updated" if method == "PUT" else None,
                                     **{"If-Match": headers["ETag"], "Destination": "/dest"})
            self.assertEqual(status, 204 if method != "MOVE" else 201)
            if method == "MOVE":
                (self.root / "dest").rename(self.root / "source")

    def test_put_detects_edit_during_final_quota_scan(self):
        original = self.server.usage
        calls = 0
        def usage():
            nonlocal calls
            calls += 1
            if calls == 2:
                (self.root / "source").write_text("local during commit")
            return original()
        with patch.object(self.server, "usage", side_effect=usage):
            self.assertEqual(self.request("PUT", body=b"remote")[0], 409)
        self.assertEqual((self.root / "source").read_text(), "local during commit")
        self.assertFalse(list(self.root.glob(".agent-upload-*")))

    def test_move_and_delete_recheck_source_version_before_mutation(self):
        for method in ("MOVE", "DELETE"):
            original = self.server.fingerprint
            reads = 0
            def fingerprint(parent, name):
                nonlocal reads
                if name == "source":
                    reads += 1
                    if reads == 2:
                        (self.root / "source").write_text("local edit " + method)
                return original(parent, name)
            with patch.object(self.server, "fingerprint", side_effect=fingerprint):
                self.assertEqual(self.request(method, Destination="/dest")[0], 409)
            self.assertEqual((self.root / "source").read_text(), "local edit " + method)
            self.assertFalse((self.root / "dest").exists())

    def test_move_rechecks_destination_version(self):
        original = self.server.fingerprint
        reads = 0
        def fingerprint(parent, name):
            nonlocal reads
            if name == "dest":
                reads += 1
                if reads == 2:
                    (self.root / "dest").write_text("local destination")
            return original(parent, name)
        with patch.object(self.server, "fingerprint", side_effect=fingerprint):
            self.assertEqual(self.request("MOVE", Destination="/dest")[0], 409)
        self.assertEqual((self.root / "dest").read_text(), "local destination")
        self.assertEqual((self.root / "source").read_text(), "original")


class MountGuardTests(unittest.TestCase):
    def test_revoke_ack_precedes_close_and_expired_lease_is_not_renewed(self):
        calls, events = [], []
        class Mount:
            workspace = "fixture"
            def __init__(self, **config): pass
            def start(self): calls.append("start")
            def renew(self): calls.append("renew")
            def revoke(self): calls.append("revoke")
            def close(self): calls.append("close")
        commands = queue.Queue()
        commands.put("revoke")
        commands.put("close")
        self.assertEqual(supervise({}, commands, events.append, threading.Event(), Mount), 0)
        self.assertEqual(calls, ["start", "revoke", "close"])
        self.assertEqual([e["state"] for e in events], ["ready", "revoked", "closed"])

    def test_guard_cleans_after_control_owner_sigkill(self):
        # Real independent processes/pipe EOF; FUSE operations are a fixture here.
        guard = '''import pathlib
import runtime.mount_guard as g
class Mount:
    workspace='fixture'
    def __init__(self, root): self.root=pathlib.Path(root)
    def start(self): (self.root/'mounted').touch()
    def renew(self): pass
    def revoke(self): pass
    def close(self):
        (self.root/'mounted').unlink()
        (self.root/'cleaned').touch()
original=g.supervise
g.supervise=lambda c,q,p,s: original(c,q,p,s,Mount)
raise SystemExit(g.main())
'''
        owner = '''import json,subprocess,sys,time
p=subprocess.Popen([sys.executable,'-u','-c',sys.argv[1]], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                   text=True,close_fds=True,start_new_session=True)
p.stdin.write(json.dumps({'root':sys.argv[2]})+'\\n'); p.stdin.flush()
assert json.loads(p.stdout.readline())['state']=='ready'
print(p.pid,flush=True)
time.sleep(30)
'''
        with tempfile.TemporaryDirectory() as tmp:
            process = subprocess.Popen([sys.executable, "-u", "-c", owner, guard, tmp], stdout=subprocess.PIPE, text=True)
            try:
                guard_pid = int(process.stdout.readline())
                self.assertTrue((Path(tmp) / "mounted").exists())
                process.kill()
                process.wait(timeout=3)
                import time
                deadline = time.monotonic() + 5
                while not (Path(tmp) / "cleaned").exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue((Path(tmp) / "cleaned").exists())
                self.assertFalse((Path(tmp) / "mounted").exists())
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=3)
                process.stdout.close()


if __name__ == "__main__":
    unittest.main()
