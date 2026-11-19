"""Actual Docker startup, command lifecycle and cgroup memory measurements."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

from runtime.docker_engine import Docker
from runtime.sandbox_manager import SandboxManager
from scripts.measure_common import environment, save_report, summarize_records

METRICS = ("cold_start_ms", "exec_lifecycle_ms", "host_python_ms", "exec_overhead_ms",
           "idle_cgroup_bytes", "python_cgroup_bytes", "python_minus_idle_bytes")


def resident_sample(engine, config, python=False):
    config = dict(config)
    config["Labels"] = {**config.get("Labels", {}), "project-a.deadline": str(time.time() + 30)}
    config["Cmd"] = (["python", "-c", "import time; print('MEASURE_READY', flush=True); time.sleep(30)"]
                     if python else ["/bin/sh", "-c", "echo MEASURE_READY; exec sleep 30"])
    started = time.perf_counter_ns()
    cid = engine.create(config)
    try:
        engine.start(cid)
        deadline = time.monotonic() + 15
        while "MEASURE_READY" not in engine.logs(cid)["stdout"]:
            if not engine.inspect(cid)["Running"] or time.monotonic() > deadline:
                raise RuntimeError("Measurement container did not become ready")
            time.sleep(0.005)
        startup_ms = (time.perf_counter_ns() - started) / 1_000_000
        stats = engine.request("GET", f"/containers/{cid}/stats?stream=false&one-shot=true")
        memory = stats.get("memory_stats", {})
        usage, limit = memory.get("usage"), memory.get("limit")
        if type(usage) is not int or usage <= 0 or type(limit) is not int:
            raise RuntimeError("Docker returned no valid cgroup memory sample")
        return startup_ms, {"usage_bytes": usage, "limit_bytes": limit,
                            "cache_bytes": memory.get("stats", {}).get("file", memory.get("stats", {}).get("cache", 0))}
    finally:
        engine.remove(cid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--image", default="project-a-sandbox:cp1")
    parser.add_argument("--output", default="results/sandbox-performance.json")
    args = parser.parse_args()
    if not 10 <= args.repeats <= 100:
        parser.error("Use 10..100 repeats")
    if os.getuid() == 0:
        parser.error("Run as a non-root user with Docker access")
    engine = Docker()
    report = {"passed": False, "environment": environment(), "image": args.image,
              "model_calls": 0, "backend": "real Docker", "raw": [],
              "semantics": {"cold_start_ms": "create+start to first ready log, cached image, 5ms poll interval; no image pull",
                            "exec_lifecycle_ms": "SandboxManager.exec end-to-end, including per-operation container create/start/logs/remove",
                            "exec_overhead_ms": "exec lifecycle minus same-host fresh Python process baseline",
                            "python_cgroup_bytes": "Docker cgroup current usage including charged file cache for idle Python container",
                            "idle_cgroup_bytes": "same configuration with sleep instead of Python; separate fresh container",
                            "python_minus_idle_bytes": "signed difference, not dockerd/shim/host total memory overhead"}}
    try:
        engine.ping()
        version = engine.request("GET", "/version")
        report["docker"] = {key: version.get(key) for key in ("Version", "ApiVersion", "KernelVersion", "Os", "Arch")}
        with tempfile.TemporaryDirectory(prefix="project-a-sandbox-measurement-") as tmp:
            root = Path(tmp)
            (root / "workspace").mkdir()
            manager = SandboxManager(engine, root, root, image=args.image, uid=os.getuid(), gid=os.getgid(),
                                     instance="measure-" + uuid.uuid4().hex, allow_local_rw=True)
            try:
                manager.provision("measure", "workspace", "rw")
                config = manager.config(manager.session("measure"), "measure", "memory", "RunCommand", {"command": "true"})
                for repeat in range(args.repeats):
                    _, idle = resident_sample(engine, config)
                    cold, python = resident_sample(engine, config, python=True)
                    started = time.perf_counter_ns()
                    subprocess.run([sys.executable, "-c", "pass"], check=True, capture_output=True, timeout=10)
                    host_ms = (time.perf_counter_ns() - started) / 1_000_000
                    started = time.perf_counter_ns()
                    result = manager.exec("measure", f"exec-{repeat}", "RunCommand", {"command": "python -c 'pass'"}, 15)
                    exec_ms = (time.perf_counter_ns() - started) / 1_000_000
                    if result.get("error") or result.get("exit_code") != 0:
                        raise RuntimeError("Measured command failed: " + json.dumps(result.get("error")))
                    report["raw"].append({"repeat": repeat + 1, "cold_start_ms": cold,
                                          "exec_lifecycle_ms": exec_ms, "host_python_ms": host_ms,
                                          "exec_overhead_ms": exec_ms - host_ms,
                                          "idle_cgroup_bytes": idle["usage_bytes"], "python_cgroup_bytes": python["usage_bytes"],
                                          "python_minus_idle_bytes": python["usage_bytes"] - idle["usage_bytes"],
                                          "idle_memory": idle, "python_memory": python})
            finally:
                manager.close()
        report["summary"] = summarize_records(report["raw"], METRICS)
        report["cleanup_completed"] = True
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        save_report(args.output, report)
    print("Sandbox measurements saved to " + args.output)
    for metric, values in report["summary"].items():
        print(f"{metric}: median={values['median']:.3f}, p95={values['p95']:.3f}, n={values['n']}")


if __name__ == "__main__":
    main()
