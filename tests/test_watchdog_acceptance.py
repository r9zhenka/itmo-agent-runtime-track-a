"""Safety and evidence checks for real Compose fault injection; no host mutations."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.check_watchdog_crash import PROBE, SERVICES, owned_services, reaped_by_watchdog, rpc_source, wait_removed


class FakeDocker:
    def __init__(self, rows):
        self.rows, self.requests = rows, []
        self.output = ""

    def request(self, method, path, body=None):
        self.requests.append((method, path))
        if method != "GET":
            raise AssertionError("Safety validation must never mutate Docker")
        return self.rows

    def inspect(self, cid):
        return {"Running": True, "Paused": False}

    def logs(self, cid):
        return {"stdout": self.output, "stderr": ""}


class WatchdogAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".project-a-check-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "workspaces").mkdir()
        self.project = "project-a-check-" + "a" * 12
        self.marker = self.root / ".acceptance-stack.json"
        self.marker.write_text(json.dumps({"project": self.project, "instance": self.project}))
        self.config = {"INSTANCE_ID": self.project, "LLM_MODE": "replay", "WORKSPACE_ROOT": str(self.root / "workspaces")}
        rows = [{"Id": str(index + 1) * 64, "Labels": {"com.docker.compose.service": service,
                 "com.docker.compose.project": self.project,
                 "com.docker.compose.project.working_dir": str(self.root)}} for index, service in enumerate(SERVICES)]
        self.engine = FakeDocker(rows)

    def test_only_complete_disposable_stack_is_authorized(self):
        found, root = owned_services(self.engine, self.root, self.project, self.config)
        self.assertEqual(set(found), set(SERVICES))
        self.assertEqual(root, self.root / "workspaces")
        self.assertTrue(all(method == "GET" for method, _ in self.engine.requests))

    def test_live_project_or_missing_marker_rejected_before_any_docker_access(self):
        for project in ("project-a-cp1", "project-a-check-user", "checkpoint1"):
            with self.assertRaises(ValueError):
                owned_services(self.engine, self.root, project, self.config)
        self.marker.unlink()
        with self.assertRaises(ValueError):
            owned_services(self.engine, self.root, self.project, self.config)
        self.assertFalse(self.engine.requests)

    def test_wrong_marker_live_mode_instance_or_external_workspace_refuses_injection(self):
        for key, value in (("LLM_MODE", "live"), ("INSTANCE_ID", "other"), ("WORKSPACE_ROOT", "/tmp")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                owned_services(self.engine, self.root, self.project, {**self.config, key: value})
        self.marker.write_text(json.dumps({"project": "other", "instance": self.project}))
        with self.assertRaises(ValueError):
            owned_services(self.engine, self.root, self.project, self.config)
        self.assertFalse(self.engine.requests)

    def test_lookalike_or_incomplete_service_set_is_not_authority_to_kill(self):
        for key, value in (("com.docker.compose.project", "project-a-cp1"),
                           ("com.docker.compose.project.working_dir", "/some/live/checkout")):
            original = self.engine.rows[0]["Labels"][key]
            self.engine.rows[0]["Labels"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                owned_services(self.engine, self.root, self.project, self.config)
            self.engine.rows[0]["Labels"][key] = original
        self.engine.rows.pop()
        with self.assertRaises(ValueError):
            owned_services(self.engine, self.root, self.project, self.config)
        self.assertTrue(all(method == "GET" for method, _ in self.engine.requests))

    def test_watchdog_evidence_requires_exact_container_and_deadline_reason(self):
        self.engine.output = 'noise\n[]\n' + json.dumps({"type": "sandbox_reaped", "container": "wrong", "reason": "deadline"})
        self.assertFalse(reaped_by_watchdog(self.engine, "watchdog", "probe"))
        self.engine.output = json.dumps({"type": "sandbox_reaped", "container": "probe", "reason": "mount_lease"})
        self.assertFalse(reaped_by_watchdog(self.engine, "watchdog", "probe"))
        self.engine.output = json.dumps({"type": "sandbox_reaped", "container": "probe", "reason": "deadline"})
        self.assertTrue(reaped_by_watchdog(self.engine, "watchdog", "probe"))

    def test_container_absence_without_watchdog_log_cannot_prove_manager_crash_cleanup(self):
        self.engine.rows = []
        with patch("scripts.check_watchdog_crash.time.time", return_value=100), \
             patch("scripts.check_watchdog_crash.time.monotonic", side_effect=(0, 0, 2)), \
             patch("scripts.check_watchdog_crash.time.sleep"):
            with self.assertRaisesRegex(AssertionError, "independent watchdog evidence"):
                wait_removed(self.engine, self.project, "sid", "probe", 100, "watchdog", True, timeout=1)
        self.assertTrue(all(method == "GET" for method, _ in self.engine.requests))

    def test_real_watchdog_log_and_absence_are_sufficient_without_manual_reap(self):
        self.engine.rows = []
        self.engine.output = json.dumps({"type": "sandbox_reaped", "container": "probe", "reason": "deadline"})
        with patch("scripts.check_watchdog_crash.time.time", return_value=100), \
             patch("scripts.check_watchdog_crash.time.monotonic", return_value=0):
            result = wait_removed(self.engine, self.project, "sid", "probe", 100, "watchdog", True)
        self.assertTrue(result["removed"])
        self.assertTrue(result["watchdog_deadline_log"])
        self.assertTrue(all(method == "GET" for method, _ in self.engine.requests))

    def test_probe_is_valid_python_and_has_a_bounded_descendant(self):
        # Parse/compile only. The probe is executed solely inside capped Docker.
        compile(PROBE, "watchdog probe", "exec")
        native = (rpc_source("provision", session_id="probe", workspace="fixture", mode="rw") + "; "
                  + rpc_source("exec", session_id="probe", operation_id="op", tool="RunCommand",
                               arguments={"command": "python stats.py data.csv"}, timeout_s=6))
        compile(native, "native manager RPC probe", "exec")
        self.assertIn("time.sleep(45)", PROBE)
        self.assertIn("crash-ready", PROBE)


if __name__ == "__main__":
    unittest.main()
