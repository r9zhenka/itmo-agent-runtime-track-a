import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.common import Fault
from runtime.harness import Harness
from runtime.sandbox_manager import SandboxManager
from tests.support import FixtureProcessEngine


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "work").mkdir()
        self.engine = FixtureProcessEngine()
        self.manager = SandboxManager(self.engine, self.root, self.root)
        self.manager.provision("s", "work", "rw")

    def tearDown(self):
        self.manager.close()
        self.engine.close()
        self.tmp.cleanup()

    def execute(self, command, op="o", timeout=3):
        return self.manager.exec("s", op, "RunCommand", {"command": command}, timeout)

    def test_idempotency_and_nonzero_exit_status(self):
        command = "echo once >> count.txt; echo OK; echo failure >&2; exit 1"
        first = self.execute(command)
        second = self.execute(command)
        self.assertEqual(first, second)
        self.assertEqual(len(self.engine.created), 1)
        self.assertEqual((self.root / "work/count.txt").read_text(), "once\n")
        self.assertEqual(first["error"]["kind"], "command")
        self.assertEqual(first["exit_code"], 1)
        self.assertEqual(first["stdout"], "OK\n")
        self.assertEqual(first["stderr"], "failure\n")
        with self.assertRaises(Fault):
            self.execute("true")

    def test_timeout_cleans_up_and_next_operation_works(self):
        result = self.execute("sleep 5", timeout=0.15)
        self.assertEqual(result["error"]["kind"], "timeout")
        self.assertFalse(self.engine.containers)
        self.assertEqual(self.execute("echo alive", op="next")["exit_code"], 0)

    def test_slow_docker_responses_cannot_be_accepted_after_deadline(self):
        for operation in ("create", "inspect", "logs"):
            original = getattr(self.engine, operation)

            def delayed(*args, **kwargs):
                value = original(*args, **kwargs)
                time.sleep(0.15)
                return value

            with self.subTest(operation=operation), patch.object(self.engine, operation, side_effect=delayed):
                result = self.execute("true", op=operation, timeout=0.1)
            self.assertEqual(result["error"]["kind"], "timeout")
            self.assertIsNone(result["exit_code"])
            self.assertFalse(self.engine.containers)

    def test_cancel_kills_background_children_and_is_idempotent(self):
        results = []
        worker = threading.Thread(target=lambda: results.append(self.execute("(sleep 1; echo leaked > leaked.txt) & wait", timeout=3)))
        worker.start()
        deadline = time.monotonic() + 2
        while not self.manager.session("s")["active"] and time.monotonic() < deadline:
            time.sleep(0.01)
        self.manager.cancel("s")
        self.manager.cancel("s")
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(results[0]["error"]["kind"], "cancelled")
        time.sleep(1.1)
        self.assertFalse((self.root / "work/leaked.txt").exists())
        self.assertFalse(self.engine.containers)
        self.manager.release("s")
        self.manager.release("s")

    def test_disposable_container_configuration_and_secret_allowlist(self):
        (self.root / "work/.git").mkdir()
        with patch.dict("os.environ", {"LLM_API_KEY": "CANARY-SECRET", "INTERNAL_TOKEN": "PRIVATE"}):
            result = self.execute("echo safe")
        self.assertEqual(result["exit_code"], 0)
        config = self.engine.created[0]
        host = config["HostConfig"]
        self.assertEqual(host["NetworkMode"], "none")
        self.assertEqual(host["CapDrop"], ["ALL"])
        self.assertTrue(host["ReadonlyRootfs"])
        self.assertEqual(config["User"], "1000:1000")
        self.assertEqual(host["PidsLimit"], 64)
        self.assertEqual(host["Memory"], 268435456)
        self.assertEqual(host["NanoCpus"], 1_000_000_000)
        self.assertIn("no-new-privileges:true", host["SecurityOpt"])
        self.assertTrue(host["Mounts"][1]["ReadOnly"])
        self.assertNotIn("CANARY-SECRET", json.dumps(config))
        self.assertNotIn("PRIVATE", json.dumps(config))
        self.assertNotIn("docker.sock", json.dumps(config))

    def test_workspaces_reject_escape_and_overlapping_sessions(self):
        for folder in ("../outside", str(self.root / "work"), "."):
            with self.subTest(folder=folder), self.assertRaises(Fault):
                self.manager.provision("other", folder, "rw")
        (self.root / "link").symlink_to(self.root / "work", target_is_directory=True)
        with self.assertRaises(Fault):
            self.manager.provision("other", "link", "rw")
        (self.root / "work/sub").mkdir()
        with self.assertRaises(Fault):
            self.manager.provision("other", "work/sub", "rw")
        self.manager.release("s")
        self.manager.provision("other", "work", "ro")
        session = self.manager.session("other")
        config = self.manager.config(session, "other", "op", "RunCommand", {"command": "true"})
        self.assertTrue(config["HostConfig"]["Mounts"][0]["ReadOnly"])

    def test_file_tools_block_escape_and_external_symlink(self):
        (self.root / "outside.txt").write_text("secret")
        (self.root / "work/link").symlink_to(self.root / "outside.txt")
        for i, path in enumerate(("../outside.txt", "link", ".git/config")):
            result = self.manager.exec("s", f"read{i}", "ReadFile", {"path": path}, 3)
            self.assertNotEqual(result["exit_code"], 0)
            self.assertNotIn("secret", result["stdout"])

    def test_parallel_separate_workspaces(self):
        (self.root / "second").mkdir()
        self.manager.provision("two", "second", "rw")
        threads = [threading.Thread(target=self.manager.exec,
                   args=(sid, "op", "WriteFile", {"path": "value", "content": sid}, 3)) for sid in ("s", "two")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertEqual((self.root / "work/value").read_text(), "s")
        self.assertEqual((self.root / "second/value").read_text(), "two")


class HarnessTests(unittest.TestCase):
    def test_step_limit_exactly_one_final_and_traces_omit_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox_calls = []

            def sandbox(op, **args):
                sandbox_calls.append(op)
                return {"v": 0, "stdout": "PRIVATE FILE CONTENT", "exit_code": 0, "error": None}

            def model(op, **args):
                return {"message": {"role": "assistant", "content": None, "tool_calls": [{"id": "tool", "function": {
                    "name": "ReadFile", "arguments": '{"path":"data.txt"}'}}]}, "usage": {"total_tokens": 5}}

            harness = Harness(sandbox, model, tmp, max_steps=2)
            sid = harness.create("create", "work", "rw")["session_id"]
            first = harness.message(sid, "message", "PRIVATE USER PROMPT")
            same = harness.message(sid, "message", "PRIVATE USER PROMPT")
            self.assertEqual(first, same)
            harness.session(sid)["current"]["thread"].join(timeout=3)
            results = harness.collect(sid)["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["error"]["kind"], "step_limit")
            self.assertEqual(results[0]["tokens"], 10)
            harness.cancel(sid)
            self.assertEqual(len(harness.collect(sid)["results"]), 1)
            trace = (Path(tmp) / (sid + ".jsonl")).read_text()
            self.assertNotIn("PRIVATE", trace)
            self.assertEqual(sandbox_calls.count("exec"), 2)

    def test_cancel_during_model_call_does_not_execute_late_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            entered, finish_model = threading.Event(), threading.Event()
            calls = []

            def sandbox(op, **args):
                calls.append(op)
                return {"v": 0}

            def model(*_, **__):
                entered.set()
                finish_model.wait(3)
                return {"message": {"role": "assistant", "tool_calls": [{"id": "x", "function": {
                    "name": "RunCommand", "arguments": '{"command":"echo late"}'}}]}}

            harness = Harness(sandbox, model, tmp)
            sid = harness.create("create", "work", "rw")["session_id"]
            harness.message(sid, "m", "hello")
            self.assertTrue(entered.wait(2))
            harness.cancel(sid)
            finish_model.set()
            harness.session(sid)["current"]["thread"].join(timeout=3)
            results = harness.collect(sid)["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["outcome"], "cancelled")
            self.assertNotIn("exec", calls)

    def test_failed_cancel_still_has_one_terminal_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            entered, finish_model = threading.Event(), threading.Event()

            def sandbox(op, **args):
                if op == "cancel":
                    raise Fault("transport", "Manager unreachable", 502)
                return {"v": 0}

            def model(*_, **__):
                entered.set()
                finish_model.wait(3)
                return {"message": {"role": "assistant", "content": "done"}}

            harness = Harness(sandbox, model, tmp)
            sid = harness.create("c", "work", "rw")["session_id"]
            harness.message(sid, "m", "hello")
            self.assertTrue(entered.wait(2))
            with self.assertRaises(Fault):
                harness.cancel(sid)
            finish_model.set()
            harness.session(sid)["current"]["thread"].join(timeout=3)
            results = harness.collect(sid)["results"]
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["outcome"], "error")
            self.assertIn("could not confirm", results[0]["error"]["message"])
