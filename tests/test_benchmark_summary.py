import json
import tempfile
import unittest
from pathlib import Path

from scripts.summarize_benchmark import load_records, markdown_report, summarize_campaign


def attempt(task="B1.1", repeat=1, passed=True, pair="custom+model-a", provider="live", **extra):
    return {"task": task, "repeat": repeat, "pass": passed, "pair_label": pair,
            "model": {"provider": provider, "model": "model-a" if provider == "live" else "fixture-v1"},
            "quality_evaluation": provider == "live", "tokens": 100 if provider == "live" else 0,
            "duration_ms": 1000, "generation_ms": 900, "error_kind": None,
            "reason": "ok" if passed else "incorrect answer", **extra}


class BenchmarkSummaryTests(unittest.TestCase):
    def test_partial_usage_marker_preserves_unknown_charges_without_error_kind(self):
        report = summarize_campaign([attempt(passed=False, usage_partial=True)], ["B1.1"], 1)
        self.assertEqual(report["usage_unknown_runs"], 1)
        self.assertEqual(report["reported_tokens_total"], 100)
        with self.assertRaisesRegex(ValueError, "usage_partial"):
            summarize_campaign([attempt(usage_partial="false")], ["B1.1"], 1)

    def test_complete_matrix_preserves_failures_repeat_rates_and_spread(self):
        rows = [attempt(task, repeat, passed=(task == "B1.1" or repeat == 2))
                for task in ("B1.1", "B1.2") for repeat in (1, 2, 3)]
        report = summarize_campaign(rows, ["B1.1", "B1.2"], 3)
        self.assertTrue(report["complete"])
        self.assertTrue(report["quality_evaluation"])
        pair = report["pairs"][0]
        self.assertEqual((pair["passed"], pair["failed"], pair["missing_runs"]), (4, 2, 0))
        self.assertEqual(pair["tasks"]["B1.2"]["passed"], 1)
        group = pair["baf"]["B1"]
        self.assertEqual([item["pass_rate_observed"] for item in group["repeat_results"]], [0.5, 1, 0.5])
        self.assertEqual(group["complete_repeat_rate_spread"]["range"], 0.5)
        self.assertAlmostEqual(group["complete_repeat_rate_spread"]["population_stddev"], 0.23570226)
        self.assertEqual(pair["failure_kinds"], {"checker_failure": 2})
        self.assertEqual(pair["reported_tokens_total"], 600)
        self.assertEqual(pair["duration_ms"]["n"], 6)
        self.assertEqual(len(pair["failures"]), 2)

    def test_partial_campaign_exposes_missing_attempts_and_expected_denominator(self):
        report = summarize_campaign([attempt()], ["B1.1", "C1"], 3)
        self.assertFalse(report["complete"])
        self.assertEqual(report["status"], "partial")
        pair = report["pairs"][0]
        self.assertEqual(pair["observed_runs"], 1)
        self.assertEqual(pair["missing_runs"], 5)
        self.assertEqual(pair["pass_rate_observed"], 1)
        self.assertEqual(pair["pass_rate_expected_lower_bound"], 1 / 6)
        self.assertIsNone(pair["complete_repeat_rate_spread"])
        self.assertEqual(pair["baf"]["C1"]["observed_runs"], 0)
        self.assertEqual(len(pair["missing_attempts"]), 5)

    def test_missing_model_failure_counts_against_quality_and_marks_usage_unknown(self):
        failure = {"task": "B1.1", "repeat": 2, "pass": False, "pair_label": "custom+model-a",
                   "quality_evaluation": False, "reason": "provider timed out", "error_kind": "model"}
        report = summarize_campaign([attempt(), failure], ["B1.1"], 2)
        pair = report["pairs"][0]
        self.assertTrue(report["complete"])
        self.assertTrue(report["quality_evaluation"])
        self.assertEqual(pair["pass_rate_observed"], 0.5)
        self.assertEqual(pair["reported_tokens_total"], 100)
        self.assertEqual(pair["usage_unknown_runs"], 1)
        self.assertFalse(pair["token_usage_complete"])
        self.assertEqual(pair["missing_duration_runs"], 1)
        self.assertEqual(pair["failure_kinds"], {"model": 1})

    def test_partial_usage_after_model_error_is_lower_bound_even_with_known_model(self):
        report = summarize_campaign([attempt(passed=False, error_kind="model", tokens=321)], ["B1.1"], 1)
        self.assertEqual(report["reported_tokens_total"], 321)
        self.assertEqual(report["usage_unknown_runs"], 1)
        self.assertFalse(report["pairs"][0]["token_usage_complete"])

    def test_replay_never_becomes_quality_and_cannot_mix_with_live(self):
        replay = attempt(provider="synthetic-replay")
        report = summarize_campaign([replay], ["B1.1"], 1)
        self.assertTrue(report["complete"])
        self.assertFalse(report["quality_evaluation"])
        self.assertIn("not a verified live-model", markdown_report(report))
        with self.assertRaisesRegex(ValueError, "Mixed live/replay"):
            summarize_campaign([attempt(), attempt(repeat=2, pair="replay-pair", provider="synthetic-replay")], ["B1.1"], 2)
        replay["quality_evaluation"] = True
        with self.assertRaisesRegex(ValueError, "Replay"):
            summarize_campaign([replay], ["B1.1"], 1)

    def test_duplicate_attempts_are_rejected_instead_of_cherry_picked(self):
        with self.assertRaisesRegex(ValueError, "Duplicate attempt"):
            summarize_campaign([attempt(passed=False), attempt()], ["B1.1"], 1)

    def test_model_changes_inside_pair_are_rejected_but_distinct_pairs_are_allowed(self):
        changed = attempt(repeat=2)
        changed["model"]["model"] = "model-b"
        with self.assertRaisesRegex(ValueError, "Model/provider changed"):
            summarize_campaign([attempt(), changed], ["B1.1"], 2)
        changed["pair_label"] = "custom+model-b"
        changed["repeat"] = 1
        report = summarize_campaign([attempt(), changed], ["B1.1"], 1)
        self.assertEqual(report["pair_count"], 2)
        self.assertTrue(report["complete"])

    def test_empty_or_all_failed_unverified_campaign_cannot_claim_quality(self):
        report = summarize_campaign([], ["B1.1"], 3, ["planned-pair"])
        self.assertEqual(report["status"], "empty")
        self.assertFalse(report["complete"])
        self.assertFalse(report["quality_evaluation"])
        self.assertEqual(report["pairs"][0]["missing_runs"], 3)
        failure = {"task": "B1.1", "repeat": 1, "pass": False, "pair_label": "planned-pair"}
        report = summarize_campaign([failure], ["B1.1"], 1)
        self.assertTrue(report["complete"])
        self.assertFalse(report["quality_evaluation"])

    def test_schema_invalid_numbers_tasks_and_repeat_indices_are_rejected(self):
        for change in ({"tokens": True}, {"tokens": -1}, {"duration_ms": float("nan")},
                       {"duration_ms": -1}, {"pass": 1}, {"repeat": True}, {"repeat": 4},
                       {"task": "B99.1"}, {"quality_evaluation": False}, {"model": None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                summarize_campaign([attempt(**change)], ["B1.1"], 3)

    def test_jsonl_malformed_or_duplicate_fields_are_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runs.jsonl"
            path.write_text(json.dumps(attempt()) + "\n")
            self.assertEqual(len(load_records([path])), 1)
            for raw in ('{"task":"B1.1", "task":"B1.2"}\n', '{"pass":NaN}\n', '{"task":', '[]\n'):
                path.write_text(raw)
                with self.assertRaises(ValueError):
                    load_records([path])

    def test_markdown_contains_all_tasks_failures_coverage_and_escaped_pipes(self):
        bad = attempt(passed=False, reason="wrong | answer\nnext line")
        report = summarize_campaign([bad], ["B1.1", "C4"], 3)
        text = markdown_report(report)
        self.assertIn("B1.1", text)
        self.assertIn("C4", text)
        self.assertIn("coverage 1/3", text)
        self.assertIn("wrong \\| answer next line", text)
        self.assertIn("Failed attempts", text)


if __name__ == "__main__":
    unittest.main()
