import json
import math
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.check_all import commands, copy_source, existing_sshd_key, replay_environment, verify_replay_results
from scripts.measure_common import summarize, summarize_records
from scripts.measure_mount_worker import METRICS, measure, payload, prepare_fixture


class MeasurementTests(unittest.TestCase):
    def test_statistics_use_nearest_rank_p95_and_preserve_signed_overhead(self):
        result = summarize(range(1, 11))
        self.assertEqual(result["n"], 10)
        self.assertEqual(result["median"], 5.5)
        self.assertEqual(result["p95"], 10)
        self.assertEqual(summarize(range(1, 101))["p95"], 95)
        self.assertEqual(summarize([-2, -1, 0])["median"], -1)

    def test_statistics_reject_empty_nonfinite_and_boolean_samples(self):
        for values in ([], [math.nan], [math.inf], [True], ["1"]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    summarize(values)
        with self.assertRaises(KeyError):
            summarize_records([{}], ["missing"])

    def test_filesystem_timings_validate_contents_and_record_all_repeats(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            prepare_fixture(root, files=2, small_bytes=16, large_bytes=64, write_bytes=32)
            report = measure(root, 10)
            self.assertEqual(len(report["raw"]), 10)
            self.assertEqual(set(report["summary"]), set(METRICS))
            self.assertEqual((root / "write.bin").read_bytes(), payload(32, 77))
            for metric in METRICS:
                self.assertEqual(report["summary"][metric]["n"], 10)
                self.assertTrue(all(record[metric] >= 0 for record in report["raw"]))

    def test_corrupted_fixture_never_becomes_performance_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fixture"
            prepare_fixture(root, files=1, small_bytes=4, large_bytes=4, write_bytes=4)
            (root / "large.bin").write_bytes(b"BAD!")
            with self.assertRaisesRegex(AssertionError, "Large-file"):
                measure(root, 10)

    def test_mount_client_verification_cannot_reuse_local_baseline_write(self):
        from scripts.measure_mount import main
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            remote = Mock(workspace="remote-" + "a" * 32, last_error=None)
            worker = {"raw": [{} for _ in range(10)], "is_mount": True, "summary": {}}
            # A worker that reports success without writing must not inherit the
            # matching final marker left by the preceding real local baseline.
            with patch("sys.argv", ["measure_mount", "--ssh-host", "fixture", "--server-repo", "/fixture",
                                    "--output", str(output)]), \
                 patch.dict(os.environ, {"CLIENT_TOKEN": "fixture-token"}), \
                 patch("scripts.measure_mount.settings", return_value={}), \
                 patch("scripts.measure_mount.RemoteClient", return_value=remote), \
                 patch("scripts.measure_mount.subprocess.run", return_value=SimpleNamespace(
                     returncode=0, stdout=json.dumps(worker))):
                with self.assertRaisesRegex(AssertionError, "Server writes were not visible"):
                    main()
            self.assertFalse(json.loads(output.read_text())["passed"])
            remote.close.assert_called_once()

    def test_replay_environment_does_not_inherit_provider_credentials(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "CANARY", "LLM_MODE": "live", "LLM_PROXY_SOCKET": "/private",
                                     "COMPOSE_FILE": "live.yml", "PYTHONPATH": "/outside"}):
            result = replay_environment(Path("/tmp/isolated"), 23456, "check-id")
        self.assertEqual(result["LLM_MODE"], "replay")
        self.assertEqual(result["LLM_API_KEY"], "")
        self.assertEqual(result["LLM_PROXY_SOCKET"], "")
        self.assertNotIn("COMPOSE_FILE", result)
        self.assertNotIn("PYTHONPATH", result)
        self.assertEqual(result["GATEWAY_PORT"], "23456")
        self.assertEqual(result["WORKSPACE_ROOT"], "/tmp/isolated/workspaces")
        self.assertEqual(result["ALLOW_LOCAL_RW"], "1")

    def test_replay_report_requires_full_coverage_success_and_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baf.jsonl"
            valid = {"task": "B1.1", "pass": True, "model": {"provider": "synthetic-replay"}, "quality_evaluation": False}
            path.write_text(json.dumps(valid) + "\n")
            verify_replay_results(path, ["B1.1"])
            for records in ([], [valid, valid], [{**valid, "pass": False}],
                            [{**valid, "model": {"provider": "live"}}], [{**valid, "quality_evaluation": True}]):
                path.write_text("\n".join(json.dumps(record) for record in records))
                with self.assertRaises(RuntimeError):
                    verify_replay_results(path, ["B1.1"])

    def test_unified_suite_contains_real_checks_without_download_commands(self):
        steps = dict(commands("python3", "/installed/rclone"))
        self.assertEqual(set(steps), {"offline-unit-cli-http", "docker-isolation", "isolated-code-grader",
                                     "adversarial-hardening", "full-synthetic-baf", "real-webdav", "mount-helper-sigkill"})
        for command in steps.values():
            self.assertNotIn("curl", command)
            self.assertNotIn("pip", command)
            self.assertNotIn("scripts.install_rclone", command)

    def test_source_copy_excludes_environment_workspaces_and_repository_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, target = Path(tmp) / "source", Path(tmp) / "target"
            source.mkdir()
            target.mkdir()
            for name in ("runtime", "client", "baf", "scripts", "tests", "contracts"):
                (source / name).mkdir()
                (source / name / "ok.py").write_text("# public source")
                (source / name / "__pycache__").mkdir()
            for name in ("Dockerfile", "sandbox.Dockerfile", "docker-compose.yml", ".env.example"):
                (source / name).write_text("template")
            (source / ".env").write_text("SECRET")
            (source / "workspaces").mkdir()
            (source / ".git").mkdir()
            copy_source(source, target)
            self.assertFalse((target / ".env").exists())
            self.assertFalse((target / "workspaces").exists())
            self.assertFalse((target / ".git").exists())
            self.assertFalse((target / "runtime/__pycache__").exists())
            self.assertTrue((target / "runtime/ok.py").exists())

    def test_temporary_ssh_key_cleanup_preserves_existing_and_concurrently_added_keys(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".ssh").mkdir()
            authorized = home / ".ssh/authorized_keys"
            authorized.write_text("ssh-ed25519 ORIGINAL original-key\n")
            host_public = home / "host.pub"
            host_public.write_text("ssh-ed25519 HOST host-key\n")

            def command(argv, **kwargs):
                if argv[0] == "ssh-keygen":
                    key = Path(argv[argv.index("-f") + 1])
                    key.write_text("PRIVATE TEST FIXTURE")
                    key.with_suffix(".pub").write_text("ssh-ed25519 TEMP generated-key\n")
                    return SimpleNamespace(returncode=0)
                self.assertEqual(argv[0], "ssh-keyscan")
                return SimpleNamespace(returncode=0, stdout="127.0.0.1 ssh-ed25519 HOST\n", stderr="")

            with patch("scripts.check_all.Path.home", return_value=home), \
                 patch("scripts.check_all.Path.glob", return_value=[host_public]), \
                 patch("scripts.check_all.subprocess.run", side_effect=command):
                with self.assertRaisesRegex(RuntimeError, "injected"):
                    with existing_sshd_key() as config:
                        self.assertTrue(config.is_file())
                        contents = authorized.read_text()
                        self.assertIn("ORIGINAL", contents)
                        self.assertIn('from="127.0.0.1"', contents)
                        with authorized.open("a") as file:
                            file.write("ssh-ed25519 CONCURRENT another-key\n")
                        raise RuntimeError("injected measurement failure")
            self.assertEqual(authorized.read_text(), "ssh-ed25519 ORIGINAL original-key\nssh-ed25519 CONCURRENT another-key\n")


if __name__ == "__main__":
    unittest.main()
