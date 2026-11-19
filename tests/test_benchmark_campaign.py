import contextlib
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import benchmark


class CampaignTests(unittest.TestCase):
    def invoke(self, runner, tasks=1, repeats=1, parallel=1, budget=1000, reserve=100, pair="label"):
        clients = []

        class Client:
            def __init__(self, *args):
                clients.append(self)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "results.jsonl"
            argv = ["benchmark", "--output", str(output), "--root", tmp, "--parallel", str(parallel),
                    "--token-budget", str(budget), "--run-token-reserve", str(reserve),
                    "--repeats", str(repeats), "--pair", pair]
            selected = [{"id": f"B{index + 1}.1"} for index in range(tasks)]
            captured = io.StringIO()
            with patch("sys.argv", argv), patch.object(benchmark, "settings", return_value={}), patch.object(
                    benchmark, "cases", return_value=selected), patch.object(benchmark, "Client", Client), patch.object(
                    benchmark, "run_case", side_effect=runner), contextlib.redirect_stdout(captured):
                status = benchmark.main()
            rows = [json.loads(line) for line in output.read_text().splitlines()]
        return status, rows, clients, captured.getvalue()

    @staticmethod
    def result(case, repeat, tokens=10, provider="live", success=True, error_kind=None):
        return {"task": case["id"], "repeat": repeat, "pass": success, "reason": "ok" if success else
                json.dumps({"kind": error_kind, "message": "test error"}), "error_kind": error_kind,
                "tokens": tokens, "model": {"provider": provider, "model": "fixture-model"}}

    def test_finished_campaign_does_not_require_budget_for_a_nonexistent_next_run(self):
        status, rows, _, _ = self.invoke(lambda client, case, root, repeat: self.result(case, repeat, tokens=10),
                                       budget=100, reserve=100)
        self.assertEqual(status, 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["campaign_tokens"], 10)

    def test_parallel_runs_have_separate_client_instances_and_all_repeats(self):
        barrier = threading.Barrier(2)
        used = []
        lock = threading.Lock()

        def runner(client, case, root, repeat):
            with lock:
                used.append(client)
            barrier.wait(timeout=3)
            return self.result(case, repeat)
        status, rows, clients, _ = self.invoke(runner, tasks=4, repeats=2, parallel=2, budget=10000)
        self.assertEqual(status, 0)
        self.assertEqual(len({id(client) for client in clients}), 8)
        self.assertEqual({id(client) for client in used}, {id(client) for client in clients})
        self.assertEqual({(row["task"], row["repeat"]) for row in rows},
                         {(f"B{index}.1", repeat) for index in range(1, 5) for repeat in (1, 2)})
        self.assertEqual(rows[-1]["campaign_tokens"], 80)

    def test_pending_runs_reserve_capacity_before_scheduling_more(self):
        barrier = threading.Barrier(2)

        def runner(client, case, root, repeat):
            barrier.wait(timeout=3)
            return self.result(case, repeat, tokens=80)
        status, rows, clients, _ = self.invoke(runner, tasks=4, parallel=2, budget=250, reserve=100)
        self.assertEqual(status, 2)
        self.assertEqual(len(clients), 2)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["campaign_budget_charged"], 160)

    def test_unknown_usage_charges_reserve_and_stops_before_more_calls(self):
        def runner(client, case, root, repeat):
            raise RuntimeError("Connection lost before usage was reported")
        status, rows, clients, _ = self.invoke(runner, tasks=3, budget=150, reserve=100)
        self.assertEqual(status, 2)
        self.assertEqual(len(clients), 1)
        self.assertFalse(rows[0]["pass"])
        self.assertFalse(rows[0]["quality_evaluation"])
        self.assertEqual(rows[0]["campaign_budget_charged"], 100)

    def test_inflight_timeout_or_transport_failure_is_not_charged_as_known_small_usage(self):
        for kind in ("timeout", "transport", "model"):
            with self.subTest(kind=kind):
                status, rows, clients, _ = self.invoke(
                    lambda client, case, root, repeat: self.result(case, repeat, tokens=10,
                                                                  success=False, error_kind=kind),
                    tasks=2, budget=150, reserve=100)
                self.assertEqual(status, 2)
                self.assertEqual(len(clients), 1)
                self.assertEqual(rows[0]["campaign_budget_charged"], 100)

    def test_pair_label_cannot_turn_replay_into_model_quality(self):
        status, rows, _, _ = self.invoke(
            lambda client, case, root, repeat: self.result(case, repeat, tokens=0, provider="synthetic-replay"),
            pair="real-model-production")
        self.assertEqual(status, 0)
        self.assertFalse(rows[0]["quality_evaluation"])
        self.assertEqual(rows[0]["model"]["provider"], "synthetic-replay")

    def test_last_failed_run_returns_failure_not_budget_exhaustion(self):
        status, rows, _, _ = self.invoke(
            lambda client, case, root, repeat: self.result(case, repeat, tokens=10,
                                                          success=False, error_kind="model"),
            budget=100, reserve=100)
        self.assertEqual(status, 1)
        self.assertEqual(len(rows), 1)
