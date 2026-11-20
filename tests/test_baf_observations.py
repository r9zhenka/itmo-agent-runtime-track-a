"""Regression tests for stream-neutral unittest observations; no live LLM/Docker."""
import copy
import tempfile
import unittest
from pathlib import Path

from baf.cases import cases, check, prepare


PASS_LOG = ("test_empty (test_totals.TotalTests.test_empty) ... ok\n"
            "test_values (test_totals.TotalTests.test_values) ... ok\n\n"
            "----------------------------------------------------------------------\n"
            "Ran 2 tests in 0.001s\n\nOK\n")


class RenameObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "workspace"
        self.case = next(case for case in cases() if case["id"] == "B4.2")
        prepare(self.case, self.root)
        for name, text in self.case["fixture"].items():
            (self.root / name).write_bytes(text.replace("calc_total", "compute_total").encode())

    def event(self, stdout="", stderr="", **changes):
        result = {"stdout": stdout, "stderr": stderr, "exit_code": 0,
                  "error": None, "truncated": False}
        result.update(changes)
        return {"type": "tool_result", "tool": "RunCommand", "result": result}

    def verdict(self, *events):
        return check(self.case, self.root, list(events))["pass"]

    def test_success_on_either_stream_with_surrounding_shell_output(self):
        for stream in ("stdout", "stderr"):
            for log in (PASS_LOG, "before\n" + PASS_LOG + "EXIT=0\n3\nCOMPILE OK\n",
                        PASS_LOG.replace("\n", "\r\n")):
                with self.subTest(stream=stream, log=repr(log)):
                    self.assertTrue(self.verdict(self.event(**{stream: log})))

    def test_missing_or_partial_test_output_does_not_pass(self):
        self.assertFalse(self.verdict())
        for text in ("", "OK\n", "Ran 2 tests", "Ran 2 tests in 0.001s\n",
                     "test_empty ... ok\ntest_values ... ok\n", "Ran 2 tests\n\nOK\n",
                     PASS_LOG.replace("Ran 2 tests", "Ran 20 tests"),
                     PASS_LOG.replace("Ran 2 tests", "Ran 0 tests")):
            with self.subTest(text=repr(text)):
                self.assertFalse(self.verdict(self.event(stdout=text)))

    def test_failed_or_skipped_summary_cannot_pass_via_zero_shell_exit(self):
        for summary in ("FAILED (failures=1)", "FAILED (errors=1)",
                        "OK (skipped=2)", "OK (expected failures=2)"):
            log = PASS_LOG.replace("\nOK\n", "\n" + summary + "\n")
            for stream in ("stdout", "stderr"):
                with self.subTest(summary=summary, stream=stream):
                    self.assertFalse(self.verdict(self.event(**{stream: log})))
        # A forged successful suffix must not conceal an explicit failure.
        for failure in ("FAILED (failures=1)\n", "FAIL: test_values\n", "ERROR: test_empty\n"):
            self.assertFalse(self.verdict(self.event(stdout=PASS_LOG, stderr=failure)))
            self.assertFalse(self.verdict(self.event(stdout=failure + PASS_LOG)))

    def test_nonzero_error_and_truncated_results_are_rejected(self):
        for changes in ({"exit_code": 1}, {"exit_code": None}, {"exit_code": False},
                        {"error": {"kind": "timeout"}}, {"error": {}},
                        {"truncated": True}):
            with self.subTest(changes=changes):
                self.assertFalse(self.verdict(self.event(stderr=PASS_LOG, **changes)))
        for key in ("error", "truncated", "stdout", "stderr"):
            event = self.event(stderr=PASS_LOG)
            del event["result"][key]
            self.assertFalse(self.verdict(event))

    def test_wrong_tool_or_malformed_result_cannot_supply_observation(self):
        for changes in ({"type": "model"}, {"tool": "ReadFile"}, {"result": None}):
            event = self.event(stdout=PASS_LOG)
            event.update(changes)
            self.assertFalse(self.verdict(event))

    def test_each_unrelated_file_mutation_still_fails(self):
        for name in self.case["fixture"]:
            with self.subTest(name=name):
                path = self.root / name
                correct = path.read_bytes()
                path.write_bytes(correct + b"# unrelated change\n")
                self.assertFalse(self.verdict(self.event(stdout=PASS_LOG)))
                path.write_bytes(correct)
        self.assertTrue(self.verdict(self.event(stdout=PASS_LOG)))

    def test_missing_or_unrenamed_source_still_fails(self):
        path = self.root / "totals.py"
        correct = path.read_bytes()
        path.write_bytes(correct.replace(b"compute_total", b"calc_total"))
        self.assertFalse(self.verdict(self.event(stdout=PASS_LOG)))
        path.unlink()
        self.assertFalse(self.verdict(self.event(stdout=PASS_LOG)))

    def test_separate_failed_attempt_does_not_hide_later_success(self):
        failed = self.event(stdout=PASS_LOG.replace("\nOK\n", "\nFAILED (failures=1)\n"), exit_code=1)
        self.assertTrue(self.verdict(failed, self.event(stdout=PASS_LOG)))
        self.assertFalse(self.verdict(failed))


class AdditionalObservationTests(unittest.TestCase):
    """Reuse trusted fixture replay; stub only the unrelated hidden code grader."""
    def setUp(self):
        import tests.test_additional_baf as fixture_helpers
        self.driver = fixture_helpers.AdditionalBAFTests()
        self.driver.setUp()
        self.addCleanup(self.driver.tearDown)

    def test_b64_c1_c3_require_success_on_either_stream(self):
        from baf.additional_checks import check as additional_check

        class AcceptedCode:
            def check(self, *args, **kwargs):
                return {"pass": True, "reason": "test stub: public-observation layer only"}

        for task, expected_count in (("B6.4", 2), ("C1", 2), ("C3", 3)):
            case, workspace, events = self.driver.replay(task)
            original_files = {str(p.relative_to(workspace)): p.read_bytes()
                              for p in workspace.rglob("*") if p.is_file()}
            test_indexes = [i for i, event in enumerate(events)
                            if f"Ran {expected_count} tests" in event["result"].get("stderr", "")]
            self.assertEqual(len(test_indexes), 1, task)
            index = test_indexes[0]
            log = events[index]["result"]["stderr"]

            def verdict(changes):
                changed = copy.deepcopy(events)
                changed[index]["result"].update(changes)
                return additional_check(case, workspace, changed, AcceptedCode())["pass"]

            for stream in ("stdout", "stderr"):
                with self.subTest(task=task, stream=stream):
                    success = {"stdout": "", "stderr": "", stream: log}
                    self.assertTrue(verdict(success))
                    for changes in ({"exit_code": 1}, {"error": {"kind": "timeout"}},
                                    {"truncated": True},
                                    {stream: log.replace("\nOK\n", "\nFAILED (failures=1)\n")},
                                    {stream: log.replace("\nOK\n", "\nOK (skipped=1)\n")},
                                    {stream: log.replace(f"Ran {expected_count} tests", "Ran 20 tests")},
                                    {stream: f"Ran {expected_count} tests"}, {stream: ""}):
                        self.assertFalse(verdict({**success, **changes}), (task, stream, changes))
            no_test = [event for i, event in enumerate(events) if i != index]
            self.assertFalse(additional_check(case, workspace, no_test, AcceptedCode())["pass"])
            self.assertEqual(original_files,
                             {str(p.relative_to(workspace)): p.read_bytes()
                              for p in workspace.rglob("*") if p.is_file()})


    def test_c3_cli_whole_stdout_line_allows_shell_markers(self):
        from baf.additional_checks import check as additional_check

        class AcceptedCode:
            def check(self, *args, **kwargs):
                return {"pass": True, "reason": "test stub: observation layer only"}

        case, workspace, events = self.driver.replay("C3")
        index = next(i for i, event in enumerate(events)
                     if event["result"].get("stdout", "").strip() == "3723")
        def verdict(changes, event_changes=None):
            changed = copy.deepcopy(events)
            changed[index]["result"].update(changes)
            changed[index].update(event_changes or {})
            return additional_check(case, workspace, changed, AcceptedCode())["pass"]

        for log in ("3723\n", "before\n3723\nEXIT=0\n", "before\r\n3723\r\nEXIT=0\r\n"):
            with self.subTest(log=log):
                self.assertTrue(verdict({"stdout": log}))
        for log in ("", "37230\n", "13723\n", "value=3723\n", "3723.0\n", " 3723 \n"):
            with self.subTest(log=log):
                self.assertFalse(verdict({"stdout": log}))
        self.assertFalse(verdict({"stdout": "", "stderr": "3723\n"}))
        for changes in ({"exit_code": 1}, {"exit_code": None}, {"exit_code": False},
                        {"error": {"kind": "timeout"}}, {"error": {}}, {"truncated": True}):
            self.assertFalse(verdict(changes), changes)
        for key in ("error", "truncated"):
            changed = copy.deepcopy(events)
            del changed[index]["result"][key]
            self.assertFalse(additional_check(case, workspace, changed, AcceptedCode())["pass"])
        self.assertFalse(verdict({}, {"tool": "ReadFile"}))
        self.assertFalse(verdict({}, {"type": "model"}))
        no_cli = [event for i, event in enumerate(events) if i != index]
        self.assertFalse(additional_check(case, workspace, no_cli, AcceptedCode())["pass"])

    def test_c3_cli_observation_does_not_replace_ast_or_hidden_grading(self):
        from baf.additional_checks import check as additional_check

        class CodeVerdict:
            def __init__(self, passed):
                self.passed, self.calls = passed, []
            def check(self, task, workspace, **kwargs):
                self.calls.append((task, kwargs))
                return {"pass": self.passed, "reason": "test hidden-grader verdict"}

        case, workspace, events = self.driver.replay("C3")
        grader = CodeVerdict(False)
        self.assertFalse(additional_check(case, workspace, events, grader)["pass"])
        self.assertEqual(grader.calls, [("C3", {"source_file": "utils/duration.py"})])
        main = workspace / "main.py"
        main.write_text("print(3723)\n")
        grader = CodeVerdict(True)
        self.assertFalse(additional_check(case, workspace, events, grader)["pass"])
        self.assertEqual(grader.calls, [])



class ProbeObservationTests(unittest.TestCase):
    def setUp(self):
        import json
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "workspace"
        self.case = next(case for case in cases() if case["id"] == "B5.4")
        prepare(self.case, self.root)
        self.answer = {"status": "degraded", "exit_code": 3, "healthy": 2,
                       "total": 3, "retry": False}
        (self.root / "answer.json").write_text(json.dumps(self.answer))
        self.json_line = '{"healthy": 2, "total": 3, "status": "degraded"}'
        self.stdout = "Checking replicas...\n" + self.json_line + "\n"
        self.warning = "one replica unavailable; no automatic retry\n"

    def direct(self):
        return {"type": "tool_result", "tool": "RunCommand", "result": {
            "exit_code": 3, "error": {"kind": "command", "message": "Nonzero exit code", "retryable": False},
            "stdout": self.stdout, "stderr": self.warning, "truncated": False}}

    def captured(self, spaced=False, last_line=False):
        out_header = "--- STDOUT ---" if spaced else "---STDOUT---"
        err_header = "--- STDERR ---" if spaced else "---STDERR---"
        text = "EXIT=3\n" + out_header + "\n" + self.stdout + err_header + "\n" + self.warning
        if last_line:
            text += "--- LAST STDOUT LINE ---\n" + self.json_line + "\n"
        return {"type": "tool_result", "tool": "RunCommand", "result": {
            "exit_code": 0, "error": None, "stdout": text, "stderr": "", "truncated": False}}

    def verdict(self, event):
        return check(self.case, self.root, [event])["pass"]

    def test_direct_and_explicit_captured_child_outputs(self):
        self.assertTrue(self.verdict(self.direct()))
        for spaced in (False, True):
            for last in (False, True):
                event = self.captured(spaced, last)
                self.assertTrue(self.verdict(event))
                event["result"]["stdout"] = event["result"]["stdout"].replace("\n", "\r\n")
                self.assertTrue(self.verdict(event))

    def test_capture_requires_exit_labels_exact_json_and_warning(self):
        captured = self.captured(True, True)
        original = captured["result"]["stdout"]
        variants = [original.replace("EXIT=3\n", ""),
                    original.replace("EXIT=3", "EXIT=0"),
                    original.replace("EXIT=3", "EXIT=30"),
                    original.replace("--- STDOUT ---\n", ""),
                    original.replace("--- STDERR ---\n", ""),
                    original.replace('"healthy": 2', '"healthy": false'),
                    original.replace('"healthy": 2', '"healthy": 2.0'),
                    original.replace('"total": 3', '"total": 4'),
                    original.replace('"status": "degraded"', '"status": "healthy"'),
                    original.replace('"healthy": 2', '"healthy": 9, "healthy": 2'),
                    original.replace(self.warning, "no automatic retry\n"),
                    original.replace("Checking replicas...\n", ""),
                    "print('EXIT=3')\n" + original,
                    original + "unlabelled extra output\n"]
        for text in variants:
            with self.subTest(text=text):
                event = copy.deepcopy(captured)
                event["result"]["stdout"] = text
                self.assertFalse(self.verdict(event))
        # Wrong repeated JSON is rejected even when the first capture is correct.
        captured["result"]["stdout"] = original.rsplit(self.json_line, 1)[0] + '{}\n'
        self.assertFalse(self.verdict(captured))
        for field, text in (("stdout", self.stdout.replace('"healthy": 2', '"healthy": false')),
                            ("stdout", ""), ("stderr", ""), ("stderr", "no automatic retry")):
            event = self.direct(); event["result"][field] = text
            self.assertFalse(self.verdict(event))

    def test_bad_protocol_status_and_readfile_or_source_are_not_evidence(self):
        for factory in (self.direct, self.captured):
            for changes in ({"exit_code": 1}, {"exit_code": None}, {"exit_code": False},
                            {"truncated": True}, {"error": {"kind": "timeout"}},
                            {"error": {"kind": "sandbox"}}, {"error": {}}):
                event = factory(); event["result"].update(changes)
                self.assertFalse(self.verdict(event), changes)
            for key in ("error", "truncated"):
                event = factory(); del event["result"][key]
                self.assertFalse(self.verdict(event))
            for changes in ({"tool": "ReadFile"}, {"type": "model"}, {"result": None}):
                event = factory(); event.update(changes)
                self.assertFalse(self.verdict(event))
        event = self.captured(); event["result"]["error"] = {"kind": "command"}
        self.assertFalse(self.verdict(event))
        event = self.captured(); event["result"]["stdout"] = self.case["fixture"]["probe.py"]
        self.assertFalse(self.verdict(event))
        self.assertFalse(check(self.case, self.root, [])["pass"])

    def test_answer_types_and_unchanged_probe_remain_independent(self):
        import json
        for factory in (self.direct, self.captured):
            answer = {**self.answer, "healthy": False}
            (self.root / "answer.json").write_text(json.dumps(answer))
            self.assertFalse(self.verdict(factory()))
        (self.root / "answer.json").write_text(json.dumps(self.answer))
        self.assertTrue(self.verdict(self.captured()))
        (self.root / "probe.py").write_text(self.case["fixture"]["probe.py"] + "# changed\n")
        self.assertFalse(self.verdict(self.direct()))
        self.assertFalse(self.verdict(self.captured()))


if __name__ == "__main__":
    unittest.main()
