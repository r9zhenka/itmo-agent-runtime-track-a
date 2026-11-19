import unittest

from baf.cases import cases, check, prepare
from baf.code_evaluator import FunctionEvaluator
from scripts.benchmark import run_case
from tests.support import stack


class BAFTests(unittest.TestCase):
    def test_all_thirty_nine_through_four_http_services(self):
        with stack() as app:
            self.assertEqual(len(cases()), 39)
            for case in cases():
                with self.subTest(task=case["id"]):
                    result = run_case(app["client"], case, app["root"],
                                      code_evaluator=FunctionEvaluator(engine=app["engine"]))
                    self.assertTrue(result["pass"], result["reason"])
                    self.assertEqual(result["model"]["provider"], "synthetic-replay")
                    self.assertEqual(result["tokens"], 0)
            self.assertFalse(app["engine"].containers)

    def test_checkers_reject_missing_outputs(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            for case in cases():
                root = Path(tmp) / case["id"]
                prepare(case, root)
                self.assertFalse(check(case, root, [])["pass"], case["id"])
