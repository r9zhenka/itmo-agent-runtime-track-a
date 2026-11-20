import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from client.api import Client
from runtime.common import Fault
from scripts import benchmark


class BenchmarkRecoveryTests(unittest.TestCase):
    @staticmethod
    def events(terminal=False):
        common = {"session_id": "session", "run_id": "run", "trace_id": "run"}
        events = [
            {**common, "seq": 1, "type": "started"},
            {**common, "seq": 2, "type": "model", "provider": "live", "model": "test-model", "tokens": 21},
            {**common, "seq": 3, "type": "tool_result", "tool": "WriteFile", "outcome": "success"},
            {**common, "seq": 4, "type": "model", "provider": "live", "model": "test-model", "tokens": 12},
        ]
        if terminal:
            events.append({**common, "seq": 5, "type": "result", "tokens": 33, "outcome": "success"})
        return events

    def run_case(self, terminal=False, cleanup_failure=False, code_task=False, final_outcome="success"):
        client = Mock()
        client.create.return_value = "session"
        client.send.return_value = "run"

        def watch(*args):
            for event in self.events(terminal):
                if event["type"] == "result":
                    event["outcome"] = final_outcome
                yield event
            if not terminal:
                raise Fault("timeout", "Stream timed out", 408)

        client.watch.side_effect = watch
        if cleanup_failure:
            client.release.side_effect = Fault("transport", "Cleanup unavailable", 503)
        case = {"id": "C3.1", "code_task": code_task}
        with tempfile.TemporaryDirectory() as tmp, patch.object(benchmark, "prepare"), patch.object(
                benchmark, "prompt", return_value="fixture prompt"), patch.object(
                benchmark, "check", return_value={"pass": True, "reason": "ok"}) as check:
            result = benchmark.run_case(client, case, tmp, repeat=2)
            self.assertEqual(Path(result["workspace"]).parent, Path(tmp))
        self.assertEqual(client.create.call_count, 1)
        self.assertEqual(client.send.call_count, 1)
        self.assertEqual(client.watch.call_count, 1)
        return result, client, check

    def assert_metadata(self, result, cursor):
        self.assertEqual(result["task"], "C3.1")
        self.assertEqual(result["repeat"], 2)
        self.assertEqual(result["session_id"], "session")
        self.assertEqual(result["trace_id"], "run")
        self.assertEqual(result["run_id"], "run")
        self.assertEqual(result["model"], {"provider": "live", "model": "test-model"})
        self.assertEqual(result["tokens"], 33)
        self.assertEqual(result["event_cursor"], cursor)
        self.assertGreaterEqual(result["duration_ms"], result["generation_ms"])
        self.assertGreaterEqual(result["generation_ms"], 0)

    def test_default_watch_accepts_result_after_old_210_second_deadline(self):
        client = Client("http://unused", "fixture")
        final = self.events(terminal=True)[-1]
        with patch("client.api.time.monotonic", side_effect=[0, 0, 300]), patch.object(
                client, "event_batch", side_effect=[[], [final]]) as batches:
            self.assertEqual(list(client.watch("session", "run")), [final])
        self.assertEqual(batches.call_count, 2)

    def test_explicit_short_watch_timeout_still_applies(self):
        client = Client("http://unused", "fixture")
        with patch("client.api.time.monotonic", side_effect=[0, 0, 300]), patch.object(
                client, "event_batch", return_value=[]), self.assertRaises(Fault) as error:
            list(client.watch("session", "run", timeout=210))
        self.assertEqual(error.exception.kind, "timeout")

    def test_watch_timeout_retains_partial_evidence_and_does_not_retry_generation(self):
        result, client, check = self.run_case()
        self.assert_metadata(result, 4)
        self.assertFalse(result["pass"])
        self.assertTrue(result["usage_partial"])
        self.assertEqual(result["error_kind"], "timeout")
        self.assertIn("Stream timed out", result["reason"])
        check.assert_not_called()
        client.release.assert_called_once_with("session")

    def test_cleanup_failure_preserves_completed_result_metadata(self):
        result, client, check = self.run_case(terminal=True, cleanup_failure=True)
        self.assert_metadata(result, 5)
        self.assertFalse(result["pass"])
        self.assertFalse(result["usage_partial"])
        self.assertEqual(result["error_kind"], "transport")
        self.assertEqual(result["cleanup_error"]["kind"], "transport")
        check.assert_called_once()
        client.release.assert_called_once_with("session")

    def test_timeout_and_cleanup_failure_keep_both_causes(self):
        result, _, _ = self.run_case(cleanup_failure=True)
        self.assert_metadata(result, 4)
        self.assertTrue(result["usage_partial"])
        self.assertEqual(result["error_kind"], "timeout")
        self.assertIn("Stream timed out", result["reason"])
        self.assertEqual(result["cleanup_error"]["kind"], "transport")

    def test_failed_release_before_code_grading_does_not_grade_unstable_workspace(self):
        result, _, check = self.run_case(terminal=True, cleanup_failure=True, code_task=True)
        self.assert_metadata(result, 5)
        self.assertFalse(result["pass"])
        self.assertFalse(result["usage_partial"])
        check.assert_not_called()

    def test_success_keeps_normal_verdict_and_complete_usage(self):
        result, client, check = self.run_case(terminal=True)
        self.assert_metadata(result, 5)
        self.assertTrue(result["pass"])
        self.assertFalse(result["usage_partial"])
        self.assertIsNone(result["error_kind"])
        self.assertNotIn("cleanup_error", result)
        self.assertEqual(result["reason"], "ok")
        client.release.assert_called_once_with("session")
        check.assert_called_once()

    def test_cancelled_terminal_without_error_retains_partial_usage(self):
        result, client, _ = self.run_case(terminal=True, final_outcome="cancelled")
        self.assert_metadata(result, 5)
        self.assertFalse(result["pass"])
        self.assertTrue(result["usage_partial"])
        self.assertIn("cancelled", result["reason"])
        client.release.assert_called_once_with("session")


if __name__ == "__main__":
    unittest.main()
