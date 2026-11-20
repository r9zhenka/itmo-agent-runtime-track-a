"""Kill controllers only in a verified disposable check-all Compose stack.

Manager loss must be cleaned by the independently running production watchdog.
Harness loss is allowed to be cleaned by the manager or watchdog. This script
never calls the reaper itself and never targets the user's normal Compose stack.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import quote

from baf.cases import cases, prepare, prompt
from client.api import Client, settings
from runtime.docker_engine import Docker
from scripts.measure_common import environment, save_report

SERVICES = ("gateway", "harness", "sandbox-manager", "sandbox-watchdog", "llm-proxy")
PROBE = """import subprocess,sys,time
from pathlib import Path
child=subprocess.Popen([sys.executable,'-c',"import time; from pathlib import Path; time.sleep(45); Path('leaked.txt').write_text('leak')"])
Path('crash-ready').write_text('ready')
child.wait()
"""


def owned_services(engine, checkout, project, config):
    """Prove stack ownership before allowing any kill/start request."""
    checkout = Path(checkout).resolve()
    marker = checkout / ".acceptance-stack.json"
    if not re.fullmatch(r"project-a-check-[0-9a-f]{12}", project):
        raise ValueError("Only a check-all generated Compose project is supported")
    if (not checkout.name.startswith(".project-a-check-") or marker.is_symlink()
            or not marker.is_file() or json.loads(marker.read_text()) != {"project": project, "instance": project}):
        raise ValueError("Missing or mismatched disposable-stack ownership marker")
    if config.get("INSTANCE_ID") != project or config.get("LLM_MODE") != "replay":
        raise ValueError("Require this isolated instance and replay-only configuration")
    root = Path(config.get("WORKSPACE_ROOT", "")).resolve()
    if root != checkout / "workspaces" or not root.is_dir():
        raise ValueError("Only this temporary checkout's workspaces are supported")
    filters = quote(json.dumps({"label": ["com.docker.compose.project=" + project]}))
    rows = engine.request("GET", "/containers/json?all=true&filters=" + filters)
    found = {}
    for row in rows:
        labels = row.get("Labels", {})
        service = labels.get("com.docker.compose.service")
        if service not in SERVICES:
            continue
        if (labels.get("com.docker.compose.project") != project
                or Path(labels.get("com.docker.compose.project.working_dir", "")).resolve() != checkout
                or service in found or not re.fullmatch(r"[0-9a-f]{64}", row.get("Id", ""))):
            raise ValueError("Compose ownership/identity does not match disposable checkout")
        state = engine.inspect(row["Id"])
        if not state.get("Running") or state.get("Paused"):
            raise ValueError("All disposable services must be running before fault injection")
        found[service] = row["Id"]
    if set(found) != set(SERVICES):
        raise ValueError("Missing disposable-stack services")
    return found, root


def execution_containers(engine, project, sid):
    filters = quote(json.dumps({"label": ["project-a.instance=" + project, "project-a.session=" + sid]}))
    rows = engine.request("GET", "/containers/json?all=true&filters=" + filters)
    return [row for row in rows if row.get("Labels", {}).get("project-a.instance") == project
            and row.get("Labels", {}).get("project-a.session") == sid]


def reaped_by_watchdog(engine, watchdog, cid):
    for line in engine.logs(watchdog)["stdout"].splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if (isinstance(event, dict) and event.get("type") == "sandbox_reaped"
                and event.get("container") == cid and event.get("reason") == "deadline"):
            return True
    return False


def wait_removed(engine, project, sid, cid, expires, watchdog, require_watchdog, timeout=12):
    if not math.isfinite(expires) or not time.time() - 2 <= expires <= time.time() + 35:
        raise ValueError("Unexpected command deadline; refuse unbounded probe")
    deadline = time.monotonic() + max(0, expires - time.time()) + timeout
    while time.monotonic() < deadline:
        if not execution_containers(engine, project, sid):
            witnessed = reaped_by_watchdog(engine, watchdog, cid)
            # Deletion can be visible just before the watchdog's log flush.
            if witnessed or not require_watchdog:
                return {"removed": True, "watchdog_deadline_log": witnessed,
                        "observed_after_deadline_seconds": round(time.time() - expires, 3)}
        time.sleep(0.05)
    raise AssertionError("Command survived its deadline or independent watchdog evidence is missing")


def service_command(checkout, project, service, code):
    return ["docker", "compose", "--project-name", project, "--file", str(checkout / "docker-compose.yml"),
            "exec", "-T", service, "python", "-c", code]


def rpc_source(op, **values):
    # Secrets are read inside the already verified test gateway, never put on argv.
    body = json.dumps(values)
    return ("import json,os; from runtime.common import Remote; "
            "rpc=Remote('http://sandbox-manager:8000',os.environ['INTERNAL_TOKEN']); "
            f"print(json.dumps(rpc({op!r},**json.loads({body!r}))))")


def restore_service(engine, cid, timeout=20):
    if not engine.inspect(cid).get("Running"):
        engine.start(cid)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        state = engine.inspect(cid)
        if state.get("Running") and state.get("Health", {}).get("Status") == "healthy":
            return
        time.sleep(0.1)
    raise AssertionError("Disposable controller did not recover its healthcheck")


def fixture_directory(root, kind):
    folder = Path(tempfile.mkdtemp(prefix="watchdog-" + kind + "-", dir=root))
    # The manager is UID 0 with ALL capabilities dropped: it cannot traverse
    # another UID's mkdtemp(0700), even though the sandbox itself owns the files.
    # Match normal BAF fixtures; no credential or user data is placed here.
    folder.chmod(0o755)
    return folder


def crash_case(engine, checkout, project, config, services, kind):
    root = checkout / "workspaces"
    folder = fixture_directory(root, kind)
    marker = folder / "crash-ready"
    sid, worker, command_id = None, None, None
    diagnostic = None
    killed = services["sandbox-manager" if kind == "manager" else "harness"]
    watchdog = services["sandbox-watchdog"]
    watchdog_started = engine.inspect(watchdog)["StartedAt"]
    detail = {"scenario": kind + " container SIGKILL", "passed": False,
              "controller": killed, "watchdog": watchdog}
    try:
        if kind == "manager":
            sid = "watchdog-" + uuid.uuid4().hex
            source = (rpc_source("provision", session_id=sid, workspace=folder.name, mode="rw") + "; "
                      + rpc_source("exec", session_id=sid, operation_id="probe", tool="RunCommand",
                                   arguments={"command": "python stats.py data.csv"}, timeout_s=6))
            (folder / "stats.py").write_text(PROBE)
            diagnostic = tempfile.TemporaryFile()
            worker = subprocess.Popen(service_command(checkout, project, "gateway", source),
                                      stdout=diagnostic, stderr=subprocess.STDOUT)
        else:
            case = next(case for case in cases() if case["id"] == "B5.1")
            folder.rmdir()  # prepare() creates a fresh fixture and refuses reuse.
            prepare(case, folder)
            (folder / "stats.py").write_text(PROBE)
            client = Client("http://127.0.0.1:" + config["GATEWAY_PORT"], config["CLIENT_TOKEN"])
            sid = client.create(folder.name)
            detail["run_id"] = client.send(sid, prompt(case))
        end = time.monotonic() + 12
        while not marker.exists() and time.monotonic() < end:
            if worker is not None and worker.poll() is not None:
                diagnostic.seek(0)
                output = diagnostic.read(4096).decode("utf-8", errors="replace")
                raise AssertionError("Native manager exec exited before the fixture became ready "
                                     f"(exit {worker.returncode}): {output}")
            time.sleep(0.05)
        rows = execution_containers(engine, project, sid)
        if not marker.is_file() or len(rows) != 1:
            raise AssertionError("Probe did not publish exactly one active execution container")
        command = rows[0]
        command_id = command["Id"]
        if command.get("Labels", {}).get("project-a.guard") != "v1" or not engine.inspect(command_id).get("Running"):
            raise AssertionError("Probe is not an active guarded production sandbox")
        expires = float(command["Labels"]["project-a.deadline"])
        detail.update(session_id=sid, execution_container=command_id, immutable_deadline=expires)
        engine.request("POST", "/containers/" + killed + "/kill?signal=KILL")
        if engine.inspect(killed).get("Running"):
            raise AssertionError("Controller container survived SIGKILL")
        detail["controller_killed"] = True
        detail.update(wait_removed(engine, project, sid, command_id, expires, watchdog, kind == "manager"))
        state = engine.inspect(watchdog)
        if not state.get("Running") or state["StartedAt"] != watchdog_started:
            raise AssertionError("Independent watchdog was stopped or restarted during the proof")
        if (folder / "leaked.txt").exists():
            raise AssertionError("Descendant published its delayed side effect")
        detail.update(watchdog_survived=True, leaked=False, passed=True)
        return detail
    finally:
        # This is recovery after the assertion, never the cleanup observation.
        # Every mutation target was verified as part of this disposable stack.
        for item in execution_containers(engine, project, sid) if sid else []:
            engine.remove(item["Id"])
        restore_service(engine, killed)
        if sid:
            result = subprocess.run(service_command(checkout, project, "gateway", rpc_source("release", session_id=sid)),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)
            # Manager restart loses its in-memory sessions; release can return 404.
            if kind == "harness" and result.returncode:
                raise AssertionError("Recovered manager could not release the probe workspace")
        if worker is not None:
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.terminate()
                worker.wait(timeout=5)
        if diagnostic is not None:
            diagnostic.close()
        # Retain only test fixtures in this disposable checkout, for diagnosis.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", default="results/watchdog-crash.json")
    args = parser.parse_args()
    checkout = Path.cwd().resolve()
    config = {**settings(), **{key: value for key, value in os.environ.items()
                             if key in ("INSTANCE_ID", "WORKSPACE_ROOT", "LLM_MODE", "GATEWAY_PORT", "CLIENT_TOKEN")}}
    engine = Docker()
    report = {"passed": False, "environment": environment(), "checks": [],
              "backend": "real isolated Compose controllers + independent production watchdog", "model_calls": 0}
    try:
        services, _ = owned_services(engine, checkout, args.project, config)
        mode = subprocess.check_output(service_command(checkout, args.project, "llm-proxy",
            "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/health'))['mode'])"),
            text=True, timeout=10).strip()
        if mode != "replay":
            raise ValueError("Refusing fault injection unless the actual LLM proxy reports replay")
        for kind in ("manager", "harness"):
            result = crash_case(engine, checkout, args.project, config, services, kind)
            report["checks"].append(result)
            print("PASS: " + result["scenario"], flush=True)
        report["passed"] = True
    except Exception as exc:
        report["error"] = type(exc).__name__ + ": " + str(exc)
        raise
    finally:
        save_report(args.output, report)


if __name__ == "__main__":
    main()
