import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.common import Fault
from runtime.gateway import Gateway
from runtime.sandbox_manager import SandboxManager
from tests.support import FixtureProcessEngine


class GatewayConcurrencyTests(unittest.TestCase):
    def test_slow_create_does_not_hold_gateway_authorization_lock(self):
        entered, resume, cancelled = threading.Event(), threading.Event(), threading.Event()
        failures = []
        def harness(op, **args):
            if op == "create":
                if args["workspace"] == "slow":
                    entered.set()
                    if not resume.wait(3):
                        raise RuntimeError("test synchronization timeout")
                return {"session_id": args["workspace"]}
            if op == "cancel":
                cancelled.set()
                return {"cancelled": True}
        gateway = Gateway(harness)
        gateway.dispatch_authenticated({"v": 0, "op": "create", "request_id": "first",
                                        "workspace": "owned", "mode": "rw"}, "alice")
        def invoke(body, principal):
            try:
                gateway.dispatch_authenticated(body, principal)
            except Exception as exc:
                failures.append(exc)
        creator = threading.Thread(target=invoke, args=({"v": 0, "op": "create", "request_id": "second",
                                                        "workspace": "slow", "mode": "rw"}, "bob"))
        canceller = threading.Thread(target=invoke, args=({"v": 0, "op": "cancel", "session_id": "owned"}, "alice"))
        creator.start()
        try:
            self.assertTrue(entered.wait(2))
            canceller.start()
            self.assertTrue(cancelled.wait(1), "slow create held unrelated session authorization")
        finally:
            resume.set()
            creator.join(3)
            if canceller.ident is not None:
                canceller.join(3)
        self.assertFalse(creator.is_alive())
        self.assertFalse(canceller.is_alive())
        self.assertEqual(failures, [])
        with self.assertRaises(Fault):
            gateway.authorize("owned", "bob")


class OperationLaunchTests(unittest.TestCase):
    def test_failed_thread_launch_is_releasable_and_retry_runs_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "work").mkdir()
            engine = FixtureProcessEngine()
            manager = SandboxManager(engine, root, root, allow_local_rw=True)
            manager.provision("s", "work", "rw")
            operation = dict(session_id="s", operation_id="op", tool="RunCommand",
                             arguments={"command": "echo once >> output"}, timeout_s=2)
            try:
                with patch("runtime.sandbox_manager.threading.Thread.start", side_effect=RuntimeError("thread limit")):
                    with self.assertRaises(Fault) as caught:
                        manager.start(**operation)
                self.assertEqual(caught.exception.status, 503)
                self.assertTrue(caught.exception.retryable)
                self.assertIsNone(manager.session("s")["pending"])
                self.assertEqual(manager.session("s")["cursors"], {})
                self.assertEqual(engine.created, [])
                accepted = manager.start(**operation)
                deadline = time.monotonic() + 3
                events = []
                while not any(e["type"] == "result" for e in events) and time.monotonic() < deadline:
                    events += manager.events("s", events[-1]["seq"] if events else 0)
                self.assertEqual(len([e for e in events if e["type"] == "result"]), 1)
                self.assertEqual(manager.start(**operation), accepted)
                with self.assertRaises(Fault) as caught:
                    manager.start(**{**operation, "arguments": {"command": "echo changed"}})
                self.assertEqual(caught.exception.status, 409)
                self.assertEqual((root / "work/output").read_text(), "once\n")
                self.assertEqual(len(engine.created), 1)
                manager.release("s")
                manager.provision("failed", "work", "rw")
                with patch("runtime.sandbox_manager.threading.Thread.start", side_effect=RuntimeError("thread limit")):
                    with self.assertRaises(Fault):
                        manager.start(**{**operation, "session_id": "failed"})
                self.assertTrue(manager.release("failed")["released"])
            finally:
                manager.close()
                engine.close()


if __name__ == "__main__":
    unittest.main()
