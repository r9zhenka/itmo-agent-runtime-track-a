import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from baf.cases import check, prepare
from baf.reasoning_cases import cases
from baf.reasoning_checks import conflict_answer, policy_answer, transfer_answer


class ReasoningBAFTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cases = {case["id"]: case for case in cases()}
        for case in self.cases.values():
            prepare(case, self.root / case["id"])

    def answer(self, identifier):
        # Replay is a manually derived answer, independent of the checker oracle.
        return json.loads(self.cases[identifier]["replay"][-1]["arguments"]["content"])

    def grade(self, identifier, answer):
        workspace = self.root / identifier
        (workspace / "answer.json").write_text(json.dumps(answer))
        return check(self.cases[identifier], workspace, [])

    def test_manual_answers_match_independent_oracles(self):
        for identifier in self.cases:
            with self.subTest(task=identifier):
                # Object field order and whitespace do not affect grading.
                answer = dict(reversed(list(self.answer(identifier).items())))
                verdict = self.grade(identifier, answer)
                self.assertTrue(verdict["pass"], verdict["reason"])

    def test_transfer_boundary_and_midnight(self):
        data = {"arrival": "2026-11-19T23:55", "walk_minutes": 15,
                "departure": "2026-11-20T00:20", "boarding_closes_minutes_before": 10}
        self.assertEqual(transfer_answer(data), {
            "can_transfer": True, "ready_at": "2026-11-20T00:10",
            "boarding_closes_at": "2026-11-20T00:10", "margin_minutes": 0})
        for walk, allowed, margin in [(14, True, 1), (16, False, -1)]:
            with self.subTest(walk=walk):
                data["walk_minutes"] = walk
                result = transfer_answer(data)
                self.assertIs(result["can_transfer"], allowed)
                self.assertEqual(result["margin_minutes"], margin)

    def test_correct_decision_with_wrong_calculation_fails(self):
        for field, value in [("margin_minutes", 2), ("ready_at", "2026-11-19T14:25"),
                             ("boarding_closes_at", "2026-11-19T14:35"), ("can_transfer", True)]:
            with self.subTest(field=field):
                answer = self.answer("B7.1")
                answer[field] = value
                self.assertFalse(self.grade("B7.1", answer)["pass"])

    def test_inherited_deny_local_allow_default_deny_and_scope(self):
        case = self.cases["B7.2"]
        data = json.loads(case["fixture"]["policy.yaml"])
        result = policy_answer(data)
        self.assertEqual(result["allowed_roles"], ["analyst", "editor", "reader"])
        by_role = {item["role"]: item for item in result["decisions"]}
        self.assertEqual(by_role["lead"], {"role": "lead", "allowed": False,
                                         "allow_rules": ["A1", "A2"], "deny_rules": ["D1"]})
        self.assertEqual(by_role["guest"], {"role": "guest", "allowed": False,
                                          "allow_rules": [], "deny_rules": []})
        # Changing the query must change which rules apply, including inherited ones.
        data["query"] = {"action": "write", "resource": "reports"}
        result = policy_answer(data)
        self.assertEqual(result["allowed_roles"], [])
        self.assertEqual(next(item for item in result["decisions"] if item["role"] == "editor")["deny_rules"], ["D2"])

    def test_role_evidence_cannot_be_missing_duplicated_or_overridden(self):
        original = self.answer("B7.2")
        changes = []
        answer = copy.deepcopy(original)
        answer["allowed_roles"].append("lead")
        changes.append(answer)
        answer = copy.deepcopy(original)
        answer["decisions"][3]["deny_rules"] = []
        changes.append(answer)
        answer = copy.deepcopy(original)
        answer["decisions"][3]["allow_rules"].append("A1")
        changes.append(answer)
        answer = copy.deepcopy(original)
        answer["decisions"].pop()
        changes.append(answer)
        for index, answer in enumerate(changes):
            with self.subTest(mutation=index):
                self.assertFalse(self.grade("B7.2", answer)["pass"])

    def test_conflicts_require_joint_context_action_resource_and_opposite_effect(self):
        case = self.cases["B7.3"]
        data = json.loads(case["fixture"]["rules.json"])
        self.assertEqual(conflict_answer(data), self.answer("B7.3"))
        data["contexts"] = [{"id": "empty", "facts": {}},
                            {"id": "safe", "facts": {"employment": "staff", "day": "weekday"}}]
        self.assertEqual(conflict_answer(data), {"conflicts": []})
        # Two witnesses for the same pair must be aggregated, not duplicated.
        data["contexts"] = [{"id": name, "facts": {"employment": "intern", "day": "weekday"}}
                            for name in ("Z", "A")]
        self.assertEqual(conflict_answer(data), {
            "conflicts": [{"rules": ["R1", "R2"], "contexts": ["A", "Z"]}]})

    def test_incomplete_or_spurious_conflicts_fail(self):
        original = self.answer("B7.3")
        mutations = [{"conflicts": []}, {"conflicts": original["conflicts"][:-1]},
                     {"conflicts": original["conflicts"] * 2},
                     {"conflicts": [{"rules": ["R1", "R5"], "contexts": ["C2"]}]}]
        answer = copy.deepcopy(original)
        answer["conflicts"][0]["contexts"] = ["C2"]
        mutations.append(answer)
        for index, answer in enumerate(mutations):
            with self.subTest(mutation=index):
                self.assertFalse(self.grade("B7.3", answer)["pass"])

    def test_strict_schema_and_types(self):
        original = self.answer("B7.1")
        for field, value in [("can_transfer", 0), ("margin_minutes", -2.0),
                             ("margin_minutes", "-2"), ("extra", "ignore me")]:
            with self.subTest(field=field, value=value):
                answer = dict(original, **{field: value})
                self.assertFalse(self.grade("B7.1", answer)["pass"])
        for answer in [None, [], True, {"can_transfer": False}]:
            self.assertFalse(self.grade("B7.1", answer)["pass"])

    def test_malformed_ambiguous_or_oversized_json_fails(self):
        case = self.cases["B7.1"]
        workspace = self.root / case["id"]
        valid = json.dumps(self.answer(case["id"]))
        for raw in [b"", b"\xff", b"not json", b"NaN", b"Infinity", b"[" * 2000,
                    (valid[:-1] + ', "can_transfer": false}').encode(),
                    valid.encode() + b" " * 65536]:
            with self.subTest(prefix=raw[:50]):
                (workspace / "answer.json").write_bytes(raw)
                self.assertFalse(check(case, workspace, [])["pass"])

    def test_edited_input_cannot_change_expected_answer(self):
        case = self.cases["B7.1"]
        workspace = self.root / case["id"]
        data = json.loads(case["fixture"]["journey.json"])
        data["walk_minutes"] = 0
        (workspace / "journey.json").write_text(json.dumps(data))
        self.assertFalse(self.grade(case["id"], transfer_answer(data))["pass"])
        self.assertTrue(self.grade(case["id"], self.answer(case["id"]))["pass"])

    def test_special_files_and_links_fail_without_blocking(self):
        case = self.cases["B7.1"]
        workspace = self.root / case["id"]
        answer = workspace / "answer.json"
        target = self.root / "outside.json"
        target.write_text(json.dumps(self.answer(case["id"])))
        for create in [lambda: answer.symlink_to(target), lambda: os.link(target, answer),
                       lambda: os.mkfifo(answer), lambda: answer.mkdir()]:
            create()
            self.assertFalse(check(case, workspace, [])["pass"])
            if answer.is_dir():
                answer.rmdir()
            else:
                answer.unlink()


if __name__ == "__main__":
    unittest.main()
