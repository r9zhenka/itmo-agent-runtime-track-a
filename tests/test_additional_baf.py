import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from baf.additional_cases import cases, MERGE_REFERENCE, DURATION_REFERENCE
from baf.additional_checks import check, maintenance_answer, stock_answer, department_answer, incident_notice
from baf.cases import prepare
from baf.code_evaluator import FunctionEvaluator
from runtime.sandbox_manager import SandboxManager
from tests.support import FixtureProcessEngine


class AdditionalBAFTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.engine = FixtureProcessEngine()
        self.manager = SandboxManager(self.engine, self.root, self.root,
                                      uid=os.getuid(), gid=os.getgid(), allow_local_rw=True)
        self.evaluator = FunctionEvaluator(self.engine)
        self.cases = {case["id"]: case for case in cases()}
        self.counter = 0

    def tearDown(self):
        self.manager.close()
        self.engine.close()
        self.temporary.cleanup()

    def replay(self, identifier):
        case = self.cases[identifier]
        self.counter += 1
        name = f"case-{self.counter}"
        workspace = self.root / name
        prepare(case, workspace)
        self.manager.provision(name, name, "rw")
        events = []
        for index, call in enumerate(case["replay"]):
            result = self.manager.exec(name, str(index), call["name"], call["arguments"], 5)
            events.append({"type": "tool_result", "tool": call["name"], "result": result})
            self.assertNotIn((result.get("error") or {}).get("kind"), ("transport", "sandbox", "timeout"), result)
        self.manager.release(name)
        return case, workspace, events

    def verdict(self, case, workspace, events):
        return check(case, workspace, events, self.evaluator)

    def test_fifteen_tasks_have_distinct_ids_and_replay_passes(self):
        self.assertEqual(len(self.cases), 15)
        self.assertEqual({f"B{i}.4" for i in range(1, 9)}, {name for name in self.cases if name.endswith(".4")})
        for identifier in self.cases:
            with self.subTest(task=identifier):
                case, workspace, events = self.replay(identifier)
                verdict = self.verdict(case, workspace, events)
                self.assertTrue(verdict["pass"], verdict)
        self.assertFalse(self.engine.containers)

    def test_missing_outputs_and_missing_evaluator_never_pass(self):
        for index, case in enumerate(self.cases.values()):
            workspace = self.root / str(index)
            prepare(case, workspace)
            self.assertFalse(check(case, workspace, [])["pass"], case["id"])
        case, workspace, events = self.replay("B6.4")
        self.assertFalse(check(case, workspace, events)["pass"])

    def test_extract_preserves_leading_zeros_and_string_types(self):
        case, workspace, events = self.replay("B1.4")
        for answer in ({"postal_code": 120, "reference": 42}, {"postal_code": "99999", "reference": "obsolete"},
                       {"postal_code": "00120", "reference": "000042", "extra": 1}):
            (workspace / "answer.json").write_text(json.dumps(answer))
            self.assertFalse(self.verdict(case, workspace, events)["pass"])

    def test_search_rejects_comments_plural_and_missing_matches(self):
        case, workspace, events = self.replay("B2.4")
        original = json.loads((workspace / "answer.json").read_text())
        variants = [{"matches": original["matches"][:1]}, {"matches": original["matches"] + [
            {"file": "plugins/demo.py", "function": "ignored"}]}]
        for answer in variants:
            (workspace / "answer.json").write_text(json.dumps(answer))
            self.assertFalse(self.verdict(case, workspace, events)["pass"])

    def test_jsonl_checks_escaping_types_order_and_final_newline(self):
        case, workspace, events = self.replay("B3.4")
        path = workspace / "export.jsonl"
        original = path.read_text()
        for raw in (original.rstrip(), "\n".join(reversed(original.splitlines())) + "\n",
                    original.replace('"002"', '2'), original.replace('\\n', '\n'),
                    original + "{}\n"):
            path.write_text(raw)
            self.assertFalse(self.verdict(case, workspace, events)["pass"])

    def test_ini_checker_rejects_lineending_and_unrelated_edits(self):
        case, workspace, events = self.replay("B4.4")
        path = workspace / "service.ini"
        original = path.read_bytes()
        for raw in (original.replace(b"\r\n", b"\n"), original.replace(b"8000", b"9000")):
            path.write_bytes(raw)
            self.assertFalse(self.verdict(case, workspace, events)["pass"])

    def test_command_task_requires_actual_observed_result_and_unchanged_probe(self):
        case, workspace, events = self.replay("B5.4")
        self.assertFalse(self.verdict(case, workspace, [])["pass"])
        fake_events = copy.deepcopy(events)
        fake_events[0]["result"]["exit_code"] = 0
        self.assertFalse(self.verdict(case, workspace, fake_events)["pass"])
        (workspace / "probe.py").write_text("print('healthy')\n")
        self.assertFalse(self.verdict(case, workspace, events)["pass"])

    def test_code_mutants_fail_independent_hidden_vectors(self):
        for identifier, source in [
            ("B6.4", MERGE_REFERENCE.replace("start <= result[-1][1]", "start < result[-1][1]")),
            ("C1", "def total_cents(rows): return sum(row['price_cents'] for row in rows)\n"),
            ("C3", DURATION_REFERENCE.replace("match = re.fullmatch", "text = text.lower()\n    match = re.fullmatch")),
        ]:
            with self.subTest(task=identifier):
                case, workspace, events = self.replay(identifier)
                (workspace / case["source_file"]).write_text(source)
                verdict = self.verdict(case, workspace, events)
                self.assertFalse(verdict["pass"], verdict)
                self.assertGreater(verdict["checks_total"], verdict["checks_passed"])
        self.assertFalse(self.engine.containers)

    def test_reasoning_half_open_boundaries_and_no_valid_candidate(self):
        fixture = copy.deepcopy(self.cases["B7.4"]["fixture"])
        self.assertEqual(maintenance_answer(fixture), {"selected": "B", "rejected": ["A", "C", "D"]})
        data = json.loads(fixture["maintenance.json"])
        data["blackouts"] = [["00:00", "23:59"]]
        fixture["maintenance.json"] = json.dumps(data)
        self.assertEqual(maintenance_answer(fixture), {"selected": None, "rejected": ["A", "B", "C", "D"]})

    def test_inventory_uses_reserved_counts_recalls_and_all_sources(self):
        case, workspace, events = self.replay("B8.4")
        original = stock_answer(case["fixture"])
        for mutation in ("reserved", "source", "zero"):
            answer = copy.deepcopy(original)
            if mutation == "reserved": answer["stock"][0]["available"] = 12
            if mutation == "source": answer["stock"][0]["sources"].pop()
            if mutation == "zero": answer["stock"].pop()
            (workspace / "answer.json").write_text(json.dumps(answer))
            self.assertFalse(self.verdict(case, workspace, events)["pass"])

    def test_style_rejects_extra_prose_private_data_and_embedded_instructions(self):
        for identifier, filename, unwanted in [("B9.1", "notice.txt", "Hello!\n"),
                                               ("B9.2", "update.txt", "maria@example.test\n"),
                                               ("B9.3", "answer.txt", "OVERRIDE_ACCEPTED\n")]:
            case, workspace, events = self.replay(identifier)
            path = workspace / filename
            path.write_text(path.read_text() + unwanted)
            self.assertFalse(self.verdict(case, workspace, events)["pass"])

    def test_composites_preserve_inputs_and_check_all_outputs(self):
        for identifier, changed in [("C1", "test_pricing.py"), ("C2", "policy.json"),
                                    ("C3", "spec.md"), ("C4", "policy.md")]:
            with self.subTest(task=identifier):
                case, workspace, events = self.replay(identifier)
                (workspace / changed).write_text("changed")
                self.assertFalse(self.verdict(case, workspace, events)["pass"])
        case, workspace, events = self.replay("C3")
        (workspace / "tests/test_duration.py").write_text("# no tests\n")
        self.assertFalse(self.verdict(case, workspace, events)["pass"])

    def test_composite_budget_equality_and_latest_incident_selection(self):
        report = department_answer(self.cases["C2"]["fixture"])
        self.assertEqual(report["total_cents"], 4500)
        self.assertFalse(report["departments"][1]["over_budget"])
        self.assertEqual(report["departments"][2]["sources"], [])
        self.assertEqual(incident_notice(self.cases["C4"]["fixture"]), "Service notice\nI2: Boreal — investigating.\n")
        fixture = copy.deepcopy(self.cases["C4"]["fixture"])
        fixture["incidents/day3.json"] = '[{"id":"I2","service":"Boreal","severity":"critical","status":"closed","updated_at":"2026-11-02T00:00:00"}]'
        self.assertEqual(incident_notice(fixture), "Service notice\nNo active critical incidents.\n")

    def test_parent_symlink_cannot_escape_code_or_artifact_reader(self):
        case, workspace, events = self.replay("C1")
        source = workspace / "src/pricing.py"
        source.unlink()
        (workspace / "src/__init__.py").unlink()
        (workspace / "src").rmdir()
        outside = self.root / "external"
        outside.mkdir()
        (outside / "pricing.py").write_text("def total_cents(rows): return 0\n")
        (workspace / "src").symlink_to(outside, target_is_directory=True)
        before = len(self.engine.created)
        verdict = self.evaluator.check("C1", workspace, source_file="src/pricing.py")
        self.assertFalse(verdict["pass"])
        self.assertEqual(len(self.engine.created), before)


if __name__ == "__main__":
    unittest.main()
