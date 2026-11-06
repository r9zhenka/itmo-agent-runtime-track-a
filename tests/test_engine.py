import json
import struct
import subprocess
import unittest
from unittest.mock import patch

from runtime.common import Fault
from runtime.docker_engine import Docker
from runtime.llm_proxy import ModelProxy
from scripts.docker_check import TEMP_DISK_COMMAND, command_failed, temporary_disk_full


class EngineTests(unittest.TestCase):
    def test_full_device_diagnostics_reach_stderr(self):
        # /dev/full deterministically returns ENOSPC without needing a mount or Docker.
        command = TEMP_DISK_COMMAND.replace("/tmp/fill", "/dev/full")
        process = subprocess.run(["/bin/sh", "-c", command], capture_output=True,
                                 text=True, timeout=3, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
        result = {"exit_code": process.returncode, "stdout": process.stdout,
                  "stderr": process.stderr,
                  "error": {"kind": "command"} if process.returncode else None}
        self.assertTrue(temporary_disk_full(result), result)
        self.assertEqual(process.stdout, "")

    def test_disk_check_rejects_unrelated_failures(self):
        for result in (
            {"exit_code": 1, "error": {"kind": "command"}, "stderr": "Permission denied"},
            {"exit_code": None, "error": {"kind": "timeout"}, "stderr": "No space left on device"},
            {"exit_code": 0, "error": None, "stderr": "No space left on device"},
            {"exit_code": 1, "error": {"kind": "command"}, "stdout": "No space left on device", "stderr": ""},
        ):
            with self.subTest(result=result):
                self.assertFalse(temporary_disk_full(result))

    def test_isolation_checks_reject_executor_errors(self):
        self.assertTrue(command_failed({"exit_code": 1, "error": {"kind": "command"}}))
        for result in ({"exit_code": 0, "error": None},
                       {"exit_code": None, "error": {"kind": "sandbox"}},
                       {"exit_code": None, "error": {"kind": "timeout"}},
                       {"exit_code": 137, "error": {"kind": "sandbox"}}):
            with self.subTest(result=result):
                self.assertFalse(command_failed(result))

    def test_docker_multiplexed_logs_are_decoded_and_bounded(self):
        def frame(channel, text):
            data = text.encode()
            return bytes([channel, 0, 0, 0]) + struct.pack(">I", len(data)) + data
        engine = Docker()
        raw = frame(1, "OK\n") + frame(2, "failure\n") + frame(1, "x" * 70000)
        with patch.object(engine, "request", return_value=raw):
            result = engine.logs("id")
        self.assertTrue(result["stdout"].startswith("OK\n"))
        self.assertEqual(len(result["stdout"]), 65536)
        self.assertEqual(result["stderr"], "failure\n")
        self.assertTrue(result["truncated"])

    def test_provider_credentials_do_not_escape_errors(self):
        proxy = ModelProxy("live", "https://model.example/v1", "CANARY-KEY", "example-model")
        with patch("runtime.llm_proxy.request_json", side_effect=Fault("transport", "CANARY-KEY leaked by provider", 502)):
            with self.assertRaises(Fault) as raised:
                proxy.dispatch({"v": 0, "op": "complete", "messages": [], "tools": []})
        self.assertNotIn("CANARY", json.dumps(raised.exception.as_dict()))

    def test_live_request_and_usage(self):
        proxy = ModelProxy("live", "https://model.example/v1", "key", "model", {"temperature": 0})
        response = {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": "done"}}], "usage": {"total_tokens": 42}}
        with patch("runtime.llm_proxy.request_json", return_value=response) as request:
            result = proxy.dispatch({"v": 0, "op": "complete", "messages": [{"role": "user", "content": "hi"}], "tools": []})
        self.assertEqual(result["usage"]["total_tokens"], 42)
        self.assertEqual(request.call_args.args[0], "https://model.example/v1/chat/completions")
        self.assertEqual(request.call_args.args[1]["temperature"], 0)
        self.assertEqual(result["provider"], "live")
