import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from client.workspace_server import WorkspaceServer
from runtime.common import Fault
from runtime.mount_lease import write_lease
from runtime.sandbox_manager import SandboxManager
from runtime.sandbox_watchdog import reap_once
from tests.support import FixtureProcessEngine


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.export = WorkspaceServer(self.root, max_bytes=10, max_entries=4)
        self.addCleanup(self.export.close)

    def request(self, method, path, body=None, chunked=False):
        conn = http.client.HTTPConnection("127.0.0.1", self.export.port, timeout=3)
        try:
            conn.request(method, path, body,
                         {"Authorization": "Bearer " + self.export.token}, encode_chunked=chunked)
            response = conn.getresponse()
            response.read()
            return response.status
        finally:
            conn.close()

    def test_aggregate_bytes_and_peak_replacement_are_bounded(self):
        self.assertEqual(self.request("PUT", "/a", b"123456"), 201)
        self.assertEqual(self.request("PUT", "/b", b"12345"), 507)
        self.assertFalse((self.root / "b").exists())
        self.assertEqual(self.request("PUT", "/a", b"abcde"), 507)
        self.assertEqual((self.root / "a").read_bytes(), b"123456")
        self.assertEqual(list(self.root.glob(".agent-upload-*")), [])
        self.assertEqual(self.request("PUT", "/a", b"abcd"), 204)
        self.assertEqual(self.request("PUT", "/b", b"123456"), 201)
        self.assertEqual(self.export.usage(), (10, 2))

    def test_chunked_upload_reservation_and_entry_quota(self):
        self.assertEqual(self.request("PUT", "/large", iter([b"123456", b"78901"]), True), 507)
        self.assertFalse((self.root / "large").exists())
        for name in ("one", "two", "three", "four"):
            self.assertEqual(self.request("MKCOL", "/" + name), 201)
        self.assertEqual(self.request("PUT", "/file", b""), 507)
        self.assertEqual(self.request("MKCOL", "/five"), 507)
        self.assertEqual(self.request("DELETE", "/one"), 204)
        self.assertEqual(self.request("PUT", "/file", b"x"), 201)

    def test_parallel_writes_cannot_spend_the_same_capacity(self):
        statuses = []
        workers = [threading.Thread(target=lambda name=name: statuses.append(
            self.request("PUT", "/" + name, b"123456"))) for name in ("one", "two")]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=4)
            self.assertFalse(worker.is_alive())
        self.assertEqual(sorted(statuses), [201, 507])
        self.assertEqual(self.export.usage(), (6, 1))

    def test_external_file_growth_is_seen_and_protected_git_is_not_exported(self):
        (self.root / ".git").mkdir()
        (self.root / ".git/objects").write_bytes(b"x" * 100)
        self.assertEqual(self.request("PUT", "/a", b"123456"), 201)
        (self.root / "local").write_bytes(b"1234")
        self.assertEqual(self.request("PUT", "/b", b"x"), 507)
        self.assertEqual(self.request("GET", "/.git/objects"), 403)
        self.assertEqual((self.root / ".git/objects").read_bytes(), b"x" * 100)


class GuardTests(unittest.TestCase):
    def test_local_write_requires_explicit_trusted_development_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "work").mkdir()
            engine = FixtureProcessEngine()
            manager = SandboxManager(engine, root, root)
            try:
                with self.assertRaises(Fault) as caught:
                    manager.provision("s", "work", "rw")
                self.assertIn("ALLOW_LOCAL_RW", str(caught.exception))
                manager.provision("s", "work", "ro")
                profile = manager.config(manager.session("s"), "s", "op", "RunCommand", {"command": "true"}, deadline=123)
                self.assertEqual(profile["Labels"]["project-a.deadline"], "123")
                self.assertEqual(profile["Labels"]["project-a.guard"], "v1")
                self.assertEqual(profile["HostConfig"]["Ulimits"][0]["Hard"], 128 * 1024 * 1024)
            finally:
                manager.close()
                engine.close()

    def test_reaper_uses_deadline_and_never_touches_unrelated_containers(self):
        class Engine:
            removed = []

            def request(self, method, path):
                return [
                    {"Id": "expired", "Labels": {"project-a.instance": "ours", "project-a.guard": "v1", "project-a.deadline": "10"}},
                    {"Id": "active", "Labels": {"project-a.instance": "ours", "project-a.guard": "v1", "project-a.deadline": "30"}},
                    {"Id": "broken", "Labels": {"project-a.instance": "ours", "project-a.guard": "v1", "project-a.deadline": "nan"}},
                    {"Id": "foreign", "Labels": {"project-a.instance": "other", "project-a.guard": "v1", "project-a.deadline": "10"}},
                    {"Id": "service", "Labels": {"project-a.instance": "ours"}},
                ]

            def remove(self, cid):
                self.removed.append(cid)
        engine = Engine()
        self.assertEqual(reap_once(engine, "ours", "/unused", now=20), [
            {"container": "expired", "reason": "deadline"}, {"container": "broken", "reason": "deadline"}])
        self.assertEqual(engine.removed, ["expired", "broken"])

    def test_reaper_removes_lost_remote_lease_without_manager_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = "remote-" + "a" * 32
            write_lease(tmp, workspace, "rw", time.time() - 1)

            class Engine:
                removed = []

                def request(self, method, path):
                    return [{"Id": "remote", "Labels": {"project-a.instance": "ours", "project-a.guard": "v1",
                             "project-a.deadline": str(time.time() + 120), "project-a.workspace": workspace,
                             "project-a.mode": "rw"}}]

                def remove(self, cid):
                    self.removed.append(cid)
            engine = Engine()
            self.assertEqual(reap_once(engine, "ours", tmp), [{"container": "remote", "reason": "mount_lease"}])
            self.assertEqual(engine.removed, ["remote"])
