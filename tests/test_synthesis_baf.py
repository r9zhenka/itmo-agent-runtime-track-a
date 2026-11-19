import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from baf.cases import check, prepare
from baf.synthesis_cases import cases
from baf.synthesis_checks import regulation_answer, sales_answer


class SynthesisBAFTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cases = {case["id"]: case for case in cases()}
        for case in self.cases.values():
            prepare(case, self.root / case["id"])

    def answer(self, identifier):
        return json.loads(self.cases[identifier]["replay"][-1]["arguments"]["content"])

    def grade(self, identifier, answer):
        workspace = self.root / identifier
        (workspace / "answer.json").write_text(json.dumps(answer, ensure_ascii=False, indent=2))
        return check(self.cases[identifier], workspace, [])

    def reject(self, identifier, mutations):
        for index, answer in enumerate(mutations):
            with self.subTest(task=identifier, mutation=index):
                self.assertFalse(self.grade(identifier, answer)["pass"])

    def test_manual_replay_answers_match_independent_checkers(self):
        for identifier in self.cases:
            with self.subTest(task=identifier):
                answer = dict(reversed(list(self.answer(identifier).items())))
                verdict = self.grade(identifier, answer)
                self.assertTrue(verdict["pass"], verdict["reason"])

    def test_sales_exact_money_refunds_boundaries_and_zero_source(self):
        fixture = copy.deepcopy(self.cases["B8.1"]["fixture"])
        answer = sales_answer(fixture)
        self.assertEqual(answer["total_kopecks"], 160060)
        sources = {item["file"]: item for item in answer["sources"]}
        self.assertEqual(sources["sales/south.csv"]["total_kopecks"], 30)
        self.assertEqual(sources["sales/east.csv"]["total_kopecks"], 120000)
        self.assertEqual(sources["sales/online.csv"]["row_count"], 0)
        fixture["sales/online.csv"] += "2026-01-01,0.01\n2026-03-31,-0.02\n2026-04-01,900.00\n"
        self.assertEqual(sales_answer(fixture)["total_kopecks"], 160059)
        # Identical transactions are distinct rows, not duplicates to discard.
        fixture["sales/online.csv"] += "2026-01-01,0.01\n"
        self.assertEqual(sales_answer(fixture)["total_kopecks"], 160060)

    def test_sales_correct_total_does_not_excuse_missing_or_wrong_sources(self):
        original = self.answer("B8.1")
        missing = copy.deepcopy(original)
        missing["sources"].pop(2)  # Omitting the zero-contribution source must fail.
        wrong = copy.deepcopy(original)
        wrong["sources"][0]["total_kopecks"] += 1
        wrong["sources"][1]["total_kopecks"] -= 1  # Same overall sum, wrong provenance.
        count = copy.deepcopy(original)
        count["sources"][0]["row_count"] = 3
        self.reject("B8.1", [missing, wrong, count, dict(original, total_kopecks=160061)])

    def test_proposals_rejections_and_discussion_are_not_decisions(self):
        original = self.answer("B8.2")
        mutations = []
        for identifier in ("D900", "D901", "D902", "D903", "D904", "D905"):
            answer = copy.deepcopy(original)
            answer["decisions"].append({"decision_id": identifier, "owner": None,
                                        "due_date": None, "sources": []})
            mutations.append(answer)
        discussion = copy.deepcopy(original)
        discussion["decisions"][0]["sources"].insert(1, {"file": "meetings/02.md", "section": "P1"})
        mutations.append(discussion)
        self.reject("B8.2", mutations)

    def test_reaffirmation_deduplication_and_citations_are_required(self):
        original = self.answer("B8.2")
        mutations = []
        missing = copy.deepcopy(original)
        missing["decisions"][0]["sources"].pop()
        mutations.append(missing)
        duplicate = copy.deepcopy(original)
        duplicate["decisions"].insert(1, copy.deepcopy(duplicate["decisions"][0]))
        mutations.append(duplicate)
        incorrect = copy.deepcopy(original)
        incorrect["decisions"][-1]["sources"][0]["section"] = "P1"
        mutations.append(incorrect)
        mutations.append({"decisions": original["decisions"][:-1]})
        self.reject("B8.2", mutations)

    def test_unassigned_owners_and_dates_cannot_be_invented(self):
        original = self.answer("B8.2")
        mutations = []
        for index, field, value in [(0, "due_date", "2026-10-10"), (1, "due_date", "2026-10-09"),
                                    (2, "owner", "Ирина"), (4, "owner", ""), (4, "due_date", "unknown")]:
            answer = copy.deepcopy(original)
            answer["decisions"][index][field] = value
            mutations.append(answer)
        self.reject("B8.2", mutations)

    def test_version_selection_effective_date_and_status(self):
        fixture = copy.deepcopy(self.cases["B8.3"]["fixture"])
        self.assertEqual(regulation_answer(fixture)["version"], "v1")
        for day, version in [("2026-10-01", "v1"), ("2026-11-30", "v1"),
                             ("2026-12-01", "v2"), ("2027-01-01", "v2")]:
            with self.subTest(day=day):
                fixture["request.json"] = json.dumps({"as_of": day})
                result = regulation_answer(fixture)
                self.assertEqual(result["version"], version)
                self.assertEqual(result["values"][0]["value"], 30 if version == "v1" else 90)
                self.assertEqual(result["differences"][0]["other_value"], 90 if version == "v1" else 30)
        catalog = json.loads(fixture["catalog.json"])
        catalog["versions"][1]["status"] = "draft"
        catalog["versions"].reverse()  # Catalog order is irrelevant.
        fixture["catalog.json"] = json.dumps(catalog)
        self.assertEqual(regulation_answer(fixture)["version"], "v1")

    def test_wrong_version_incomplete_differences_and_bad_citations_fail(self):
        original = self.answer("B8.3")
        later = copy.deepcopy(self.cases["B8.3"]["fixture"])
        later["request.json"] = json.dumps({"as_of": "2026-12-01"})
        future = regulation_answer(later)
        future["as_of"] = original["as_of"]
        missing = copy.deepcopy(original)
        missing["differences"].pop()
        unchanged = copy.deepcopy(original)
        unchanged["differences"].append({"clause_id": "C3", "unit": "region", "selected_value": "EU",
                                         "other_value": "EU", "selected_source": "regulations/v1.md",
                                         "other_source": "regulations/v2.md"})
        wrong_source = copy.deepcopy(original)
        wrong_source["differences"][0]["other_source"] = "regulations/v1.md"
        mixed = copy.deepcopy(original)
        mixed["values"][0]["value"] = 90
        self.reject("B8.3", [future, missing, unchanged, wrong_source, mixed])

    def test_edited_inputs_and_replay_cannot_redefine_expected_output(self):
        for identifier, case in self.cases.items():
            with self.subTest(task=identifier):
                workspace = self.root / identifier
                for filename in case["fixture"]:
                    (workspace / filename).write_text("Agent changed the input")
                answer = self.answer(identifier)
                case["replay"][-1]["arguments"]["content"] = "{}"
                self.assertFalse(self.grade(identifier, {})["pass"])
                self.assertTrue(self.grade(identifier, answer)["pass"])

    def test_strict_schema_types_and_duplicate_json_keys(self):
        original = self.answer("B8.1")
        self.reject("B8.1", [dict(original, total_kopecks=160060.0),
                             dict(original, total_kopecks="160060"), dict(original, extra=True),
                             [], None, {"total_kopecks": 160060}])
        case = self.cases["B8.1"]
        workspace = self.root / case["id"]
        raw = json.dumps(original)
        for content in [raw[:-1] + ', "total_kopecks": 160060}', "NaN", "Infinity", "[" * 2000,
                        raw + " " * 65536, "not json", ""]:
            (workspace / "answer.json").write_text(content)
            self.assertFalse(check(case, workspace, [])["pass"])
        zero = copy.deepcopy(original)
        zero["sources"][2]["row_count"] = False
        self.assertFalse(self.grade("B8.1", zero)["pass"])

    def test_special_outputs_are_rejected_without_blocking(self):
        case = self.cases["B8.1"]
        workspace = self.root / case["id"]
        answer = workspace / "answer.json"
        outside = self.root / "external.json"
        outside.write_text(json.dumps(self.answer(case["id"])))
        for create in [lambda: answer.symlink_to(outside), lambda: os.link(outside, answer),
                       lambda: os.mkfifo(answer), lambda: answer.mkdir()]:
            create()
            self.assertFalse(check(case, workspace, [])["pass"])
            if answer.is_dir():
                answer.rmdir()
            else:
                answer.unlink()


if __name__ == "__main__":
    unittest.main()
