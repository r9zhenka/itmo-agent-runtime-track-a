"""Post-hoc regrade integrity tests; all evaluator calls are explicitly injected."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.regrade_observations import AFFECTED, final_event, main, regrade, snapshot_files


class RegradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspaces"
        self.root.mkdir()
        self.registry = [{"id": identifier, "fixture": {"input.txt": "fixture\n"},
                          **({"source_file": "solution.py"} if identifier in ("B6.4", "C1") else {}),
                          **({"source_file": "utils/duration.py"} if identifier == "C3" else {})}
                         for identifier in (*sorted(AFFECTED), "B1.1")]
        self.records, self.events, self.calls = [], {}, []
        self.grader = object()
        for number, case in enumerate(self.registry):
            for repeat in range(1, 4):
                sid, trace = f"s-{number}-{repeat}", f"t-{number}-{repeat}"
                folder = self.root / f"baf-{case['id'].replace('.', '-')}-{number * 3 + repeat:010x}"
                folder.mkdir()
                files = {**case["fixture"]}
                if case.get("source_file"):
                    files[case["source_file"]] = "raise RuntimeError('CANDIDATE MUST NEVER EXECUTE ON HOST')\n"
                if case["id"] == "C3":
                    files["tests/test_duration.py"] = "# public tests captured as data\n"
                if case["id"] == "B5.4":
                    files["answer.json"] = '{"healthy":2}\n'
                for name, data in files.items():
                    path = folder / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(data)
                record = {"task": case["id"], "repeat": repeat, "pair_label": "custom+live",
                          "pass": repeat == 1, "reason": "ok" if repeat == 1 else "observation failed",
                          "duration_ms": 901.25, "generation_ms": 800.5, "tokens": 42,
                          "model": {"provider": "live", "model": "fixed-model"}, "quality_evaluation": True,
                          "session_id": sid, "trace_id": trace, "workspace": str(folder),
                          "error_kind": None, "check_ms": 31, "checks_passed": 2}
                self.records.append(record)
                self.events[sid] = [
                    {"type": "model", "seq": 1, "session_id": sid, "trace_id": trace,
                     "run_id": trace, "provider": "live", "model": "fixed-model"},
                    {"type": "result", "seq": 2, "session_id": sid, "trace_id": trace,
                     "run_id": trace, "tokens": 42, "outcome": "success"}]

    def checker(self, case, workspace, events, grader):
        self.assertIs(grader, self.grader)
        self.assertNotEqual(workspace.parent, self.root)  # Immutable captured data, not live workspace.
        self.assertEqual((workspace / "input.txt").read_text(), "fixture\n")
        self.calls.append((case["id"], events[-1]["session_id"]))
        return {"pass": True, "reason": "ok", "checker_backend": "injected-test", "check_ms": 7}

    def run_regrade(self, **kwargs):
        return regrade(self.records, self.events, self.root, self.grader, "checker-fix-commit",
                       registry=self.registry, checker=self.checker, **kwargs)

    def test_uniform_scope_preserves_all_original_metrics_and_nonaffected_records(self):
        original, events = copy.deepcopy(self.records), copy.deepcopy(self.events)
        rows, audit, snapshots = self.run_regrade()
        self.assertEqual(len(self.calls), 15)
        self.assertEqual(audit["regraded"], 15)
        self.assertEqual(audit["untouched"], 3)
        self.assertEqual(audit["model_calls"], 0)
        self.assertEqual(len(audit["changed_verdicts"]), 10)
        self.assertEqual(len(snapshots), 15)
        self.assertEqual(self.records, original)
        self.assertEqual(self.events, events)
        for before, after in zip(original, rows):
            if before["task"] not in AFFECTED:
                self.assertEqual(before, after)
                continue
            self.assertTrue(after["pass"])
            for key, value in before.items():
                if key not in ("pass", "reason"):
                    self.assertEqual(value, after[key], key)
            self.assertEqual(after["original_verdict"]["pass"], before["pass"])
            self.assertEqual(after["regrade_verdict"]["check_ms"], 7)
            self.assertGreaterEqual(after["regrade_check_ms"], 0)
        c3 = next(s for s in snapshots if s["task"] == "C3")
        self.assertIn("tests/test_duration.py", c3["files"])
        self.assertIn("CANDIDATE MUST NEVER EXECUTE", c3["files"]["utils/duration.py"]["utf8"])
        b54 = next(s for s in snapshots if s["task"] == "B5.4")
        self.assertIn("answer.json", b54["files"])

    def test_runtime_and_cleanup_errors_remain_failures_even_when_new_checker_passes(self):
        first, second = self.records[:2]
        first.update({"pass": False, "reason": "provider timed out", "error_kind": "timeout"})
        self.events[first["session_id"]][-1].update(outcome="error", error={"kind": "timeout"})
        second.update({"pass": False, "reason": "cleanup failed", "error_kind": "transport"})
        rows, _, _ = self.run_regrade()
        for index in (0, 1):
            self.assertFalse(rows[index]["pass"])
            self.assertTrue(rows[index]["regrade_verdict"]["pass"])
            self.assertEqual(rows[index]["reason"], self.records[index]["reason"])
            self.assertTrue(rows[index]["regrade_runtime_failure_preserved"])

    def test_new_checker_failure_can_demote_an_original_pass(self):
        def failed(case, root, events, grader):
            return {"pass": False, "reason": "hidden vector failed"}
        rows, audit, _ = regrade(self.records, self.events, self.root, self.grader, "fix",
                                registry=self.registry, checker=failed)
        self.assertFalse(rows[0]["pass"])
        self.assertEqual(rows[0]["original_verdict"]["pass"], True)
        self.assertTrue(any(item["original"]["pass"] and not item["corrected"]["pass"]
                            for item in audit["changed_verdicts"]))

    def test_incomplete_duplicate_or_partial_event_campaign_rejected_before_grading(self):
        for records, events in ((self.records[:-1], self.events),
                                (self.records + [self.records[0]], self.events),
                                (self.records, {k: v for k, v in self.events.items() if k != self.records[0]["session_id"]})):
            with self.subTest(records=len(records), events=len(events)):
                with self.assertRaises(ValueError):
                    regrade(records, events, self.root, self.grader, "fix", registry=self.registry, checker=self.checker)
                self.assertFalse(self.calls)

    def test_final_result_requires_exact_identity_tokens_count_and_full_order(self):
        record = self.records[0]
        original = self.events[record["session_id"]]
        for key, value in (("tokens", 43), ("tokens", True), ("session_id", "other"),
                           ("trace_id", "other"), ("run_id", "other"), ("seq", 4)):
            events = copy.deepcopy(original)
            events[-1][key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    final_event(record, events)
        for events in (original[:-1], original + [original[-1]], original[1:], list(reversed(original))):
            with self.assertRaises(ValueError):
                final_event(record, events)
        events = copy.deepcopy(original)
        events[0]["model"] = "different-model"
        with self.assertRaises(ValueError):
            final_event(record, events)

    def test_outside_paths_traversal_and_symlink_workspaces_are_rejected(self):
        row = self.records[0]
        folder = Path(row["workspace"])
        for invalid in (str(Path(self.temp.name) / folder.name), str(self.root / ".." / folder.name),
                        str(self.root), str(self.root / "baf-wrong-0000000001")):
            row["workspace"] = invalid
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.run_regrade()
        row["workspace"] = str(folder)
        moved = Path(self.temp.name) / "outside"
        folder.rename(moved)
        folder.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.run_regrade()
        self.assertFalse(self.calls)

    def test_missing_unsafe_or_nonutf8_snapshot_files_fail_without_exposing_targets(self):
        case = self.registry[0]
        folder = Path(self.records[0]["workspace"])
        target = folder / "input.txt"
        target.unlink()
        secret = Path(self.temp.name) / "canary"
        secret.write_text("DO NOT COPY")
        target.symlink_to(secret)
        capture = snapshot_files(case, folder)
        self.assertNotIn("DO NOT COPY", json.dumps(capture))
        self.assertIn("read_error", capture["input.txt"])
        # Checker stub is deliberately permissive: unsafe/missing data still forces failure.
        def permissive(*args):
            return {"pass": True, "reason": "ok"}
        for mode in ("symlink", "missing", "nonutf8"):
            if mode != "symlink":
                target.unlink(missing_ok=True)
            if mode == "nonutf8":
                target.write_bytes(b"\xff")
            rows, _, snapshots = regrade(self.records, self.events, self.root, self.grader, "fix",
                                        registry=self.registry, checker=permissive)
            self.assertFalse(rows[0]["pass"])
            self.assertIn("read_error", snapshots[0]["files"]["input.txt"])

    def test_changed_live_workspace_prevents_publication(self):
        folder = Path(self.records[0]["workspace"])
        def racing(case, workspace, events, grader):
            (folder / "input.txt").write_text("changed while grading")
            return {"pass": True, "reason": "ok"}
        with self.assertRaisesRegex(ValueError, "changed during regrading"):
            regrade(self.records, self.events, self.root, self.grader, "fix",
                    registry=self.registry, checker=racing)

    def test_cli_refuses_to_overwrite_inputs_or_existing_outputs_before_docker(self):
        source = Path(self.temp.name) / "original.jsonl"
        source.write_text("original preserved")
        events = Path(self.temp.name) / "events.json"
        events.write_text("events preserved")
        for output in (source, events):
            with patch("sys.argv", ["regrade", "--input", str(source), "--events", str(events),
                                    "--output", str(output), "--checker-revision", "fix"]), \
                 patch("scripts.regrade_observations.FunctionEvaluator") as evaluator:
                with self.assertRaises(SystemExit):
                    main()
                evaluator.assert_not_called()
        self.assertEqual(source.read_text(), "original preserved")
        self.assertEqual(events.read_text(), "events preserved")


if __name__ == "__main__":
    unittest.main()
