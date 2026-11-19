import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from baf.cases import check, prepare
from baf.code_cases import REFERENCES, cases
from baf.code_evaluator import FunctionEvaluator, same_json
from runtime.common import Fault
from runtime.docker_engine import Docker
from tests.support import FixtureProcessEngine


class CodeBAFTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.engine = FixtureProcessEngine()
        self.evaluator = FunctionEvaluator(self.engine)

    def tearDown(self):
        self.engine.close()
        self.tmp.cleanup()

    def evaluate(self, identifier, source):
        case = next(c for c in cases() if c["id"] == identifier)
        folder = self.root / ("work-" + str(len(list(self.root.iterdir()))))
        prepare(case, folder)
        (folder / "solution.py").write_text(source)
        # Changing the public tests must never change the independent verdict.
        (folder / "test_public.py").write_text("# all public checks removed\n")
        return check(case, folder, [], self.evaluator)

    def test_references_and_grading_configuration(self):
        for case in cases():
            with self.subTest(task=case["id"]):
                result = self.evaluate(case["id"], REFERENCES[case["id"]])
                self.assertTrue(result["pass"], result)
                self.assertEqual(result["checks_passed"], result["checks_total"])
                self.assertEqual(result["checker_backend"], "test-only-fixture")
        self.assertFalse(self.engine.containers)
        for config in self.engine.created:
            host = config["HostConfig"]
            self.assertEqual(host["NetworkMode"], "none")
            self.assertTrue(host["ReadonlyRootfs"])
            self.assertEqual(len(host["Mounts"]), 1)
            self.assertTrue(host["Mounts"][0]["ReadOnly"])
            self.assertNotEqual(config["User"].split(":")[0], "0")
            self.assertTrue(config["Labels"]["project-a.instance"].startswith("baf-check-"))
        for folder in self.root.iterdir():
            self.assertEqual({p.name for p in folder.iterdir()}, {"task.md", "test_public.py", "solution.py"})

    def test_missing_invalid_and_public_only_solutions_fail(self):
        for source in (
            "def slugify(:\n",  # Syntax error.
            "def other(text): return text\n",  # Missing interface.
            "def slugify(text): return 42\n",
            "def slugify(text): raise ValueError('bad')\n",
            "def slugify(text): return {'Hello World':'hello-world', '  A___B! ':'a-b'}.get(text, '')\n",
            "print('{\"pass\":true}')\ndef slugify(text): return ''\n",
        ):
            with self.subTest(source=source):
                result = self.evaluate("B6.1", source)
                self.assertFalse(result["pass"], result)

    def test_log_and_calendar_mutants_fail_hidden_cases(self):
        bad_logs = REFERENCES["B6.2"].replace("bucket['errors'] += int(level == 'ERROR')", "bucket['errors'] += 1")
        bad_dates = REFERENCES["B6.3"].replace("date.fromisoformat(day)", "pass")
        for identifier, source in (("B6.2", bad_logs), ("B6.3", bad_dates)):
            with self.subTest(task=identifier):
                self.assertFalse(self.evaluate(identifier, source)["pass"])

    def test_hang_is_bounded_and_container_removed(self):
        self.evaluator.timeout = 0.2
        result = self.evaluate("B6.1", "def slugify(text):\n    while True: pass\n")
        self.assertFalse(result["pass"])
        self.assertEqual(result["checks_run"], 1)
        self.assertEqual(result["checks"][0]["reason"], "execution: timeout")
        self.assertFalse(self.engine.containers)

    def test_large_output_cannot_be_used_as_verdict(self):
        result = self.evaluate("B6.1", "def slugify(text):\n    print('x' * 70000)\n    return ''\n")
        self.assertFalse(result["pass"])
        self.assertEqual(result["checks"][0]["reason"], "output exceeded limit")

    def test_no_evaluator_never_counts_as_success(self):
        case = cases()[0]
        prepare(case, self.root / "work")
        (self.root / "work/solution.py").write_text(REFERENCES["B6.1"])
        self.assertFalse(check(case, self.root / "work", [])["pass"])

    def test_unavailable_docker_never_falls_back_to_host_execution(self):
        marker = self.root / "HOST-EXECUTED"
        folder = self.root / "work"
        folder.mkdir()
        (folder / "solution.py").write_text(f"from pathlib import Path\nPath({str(marker)!r}).touch()\n")
        engine = Mock(spec=Docker)
        engine.ping.side_effect = Fault("sandbox", "Docker unavailable", 503)
        result = FunctionEvaluator(engine).check("B6.1", folder)
        self.assertFalse(result["pass"])
        self.assertFalse(marker.exists())
        engine.create.assert_not_called()

    def test_nonregular_oversized_and_symlink_sources_are_rejected(self):
        folder = self.root / "work"
        folder.mkdir()
        path = folder / "solution.py"
        path.symlink_to(self.root / "outside")
        (self.root / "outside").write_text(REFERENCES["B6.1"])
        self.assertFalse(self.evaluator.check("B6.1", folder)["pass"])
        path.unlink()
        os.mkfifo(path)
        self.assertFalse(self.evaluator.check("B6.1", folder)["pass"])
        path.unlink()
        path.write_bytes(b"x" * 65537)
        self.assertFalse(self.evaluator.check("B6.1", folder)["pass"])
        self.assertEqual(self.engine.created, [])

    def test_json_comparison_does_not_accept_bool_or_float_for_integer(self):
        self.assertFalse(same_json({"count": True}, {"count": 1}))
        self.assertFalse(same_json({"count": 1.0}, {"count": 1}))
        self.assertTrue(same_json({"b": 2, "a": 1}, {"a": 1, "b": 2}))

    def test_return_type_is_not_coerced_to_pass(self):
        source = REFERENCES["B6.3"] + "\n_original = normalize_records\ndef normalize_records(records): return tuple(_original(records))\n"
        result = self.evaluate("B6.3", source)
        self.assertFalse(result["pass"])
        self.assertTrue(all(c["reason"] == "execution: command" for c in result["checks"]))
