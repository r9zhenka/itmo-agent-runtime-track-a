import ast
import shlex
import unittest
from unittest.mock import patch

from runtime.common import Fault
from runtime.docker_engine import Docker
from scripts.hardening_check import CPU, FILE_LIMIT, MEMORY, PIDS, python_command


class RemovalTests(unittest.TestCase):
    def test_resource_probe_shell_arguments_and_nested_python_are_valid(self):
        # Compiling the containing module alone does not validate code held in
        # strings. Do not execute any stress workload on the test host.
        for name, source in (("CPU", CPU), ("PIDS", PIDS), ("MEMORY", MEMORY), ("FILE_LIMIT", FILE_LIMIT)):
            with self.subTest(probe=name):
                command = shlex.split(python_command(source))
                self.assertEqual(command[:2], ["python", "-c"])
                self.assertEqual(len(command), 3)
                self.assertEqual(command[2], source)
                compile(command[2], name, "exec")
        nested = next(node.value.value for node in ast.walk(ast.parse(CPU))
                      if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "code"
                                                             for target in node.targets))
        compile(nested, "CPU nested worker", "exec")

    def test_concurrent_removal_is_confirmed_by_success_or_not_found(self):
        engine = Docker()
        for final in (None, Fault("sandbox", "Docker operation failed (HTTP 404)", 503)):
            with self.subTest(final=final), patch.object(engine, "request", side_effect=[
                    Fault("sandbox", "Docker operation failed (HTTP 409)", 503), final]) as request, patch(
                    "runtime.docker_engine.time.sleep"):
                engine.remove("ours")
                self.assertEqual(request.call_count, 2)
                self.assertTrue(all(call.args == ("DELETE", "/containers/ours?force=true&v=true")
                                    for call in request.call_args_list))

    def test_stuck_removal_is_bounded_and_not_reported_as_success(self):
        engine = Docker()
        with patch.object(engine, "request", side_effect=Fault(
                "sandbox", "Docker operation failed (HTTP 409)", 503)), patch(
                "runtime.docker_engine.time.monotonic", side_effect=[0, 3]):
            with self.assertRaises(Fault):
                engine.remove("ours")

    def test_other_errors_are_not_retried_or_hidden(self):
        engine = Docker()
        with patch.object(engine, "request", side_effect=Fault(
                "sandbox", "Docker daemon unavailable", 503)) as request:
            with self.assertRaises(Fault):
                engine.remove("ours")
            self.assertEqual(request.call_count, 1)
