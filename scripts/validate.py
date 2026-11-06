"""Run offline validation and persist an honest machine-readable summary."""
import datetime
import json
import platform
import unittest
from pathlib import Path


def main():
    suite = unittest.defaultTestLoader.discover("tests")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    summary = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "python": platform.python_version(), "command": "python3 -m scripts.validate",
        "make_target": "test-ci",
        "tests_run": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "passed": result.wasSuccessful(),
        "executor": "test-only local fixture process executor; NOT Docker isolation",
        "model": "synthetic-replay", "live_model_evaluated": False,
        "docker_integration_executed": False,
    }
    target = Path("results/validation.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(summary, indent=2) + "\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
