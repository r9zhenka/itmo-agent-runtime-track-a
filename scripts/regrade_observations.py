"""Regrade frozen attempts after the documented stdout/stderr observation fix.

No generation is repeated. Only B4.2, B5.4, B6.4, C1 and C3 are regraded, uniformly
across all repetitions. Candidate files are bounded UTF-8 data; generated code
can execute only inside the existing Docker FunctionEvaluator.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from baf.artifacts import read_file
from baf.cases import cases, check
from baf.code_evaluator import FunctionEvaluator
from baf.json_output import invalid_constant, unique_object
from scripts.summarize_benchmark import load_records, validate_records

AFFECTED = frozenset(("B4.2", "B5.4", "B6.4", "C1", "C3"))
SOURCE_REVISION = "9555ba99600d7f217921f9614655c48a60b5bc7e"
VERDICT_KEYS = ("pass", "reason", "checker_backend", "checks_passed", "checks_total",
                "checks_run", "checks", "check_ms")
CHECKER_FILES = ("runtime/code_worker.py", "runtime/common.py", "runtime/contracts.py",
                 "runtime/sandbox_manager.py", "runtime/docker_engine.py", "runtime/mount_lease.py",
                 "scripts/measure_common.py", "scripts/summarize_benchmark.py",
                 "scripts/regrade_observations.py")


def checker_files(repo):
    return sorted(set(CHECKER_FILES) | {str(path.relative_to(repo)) for path in (repo / "baf").glob("*.py")})


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def final_event(record, events):
    """Reject incomplete, duplicated, mixed-session or mismatched observations."""
    if not isinstance(events, list) or not events:
        raise ValueError("Missing full session events")
    sid, trace = record.get("session_id"), record.get("trace_id")
    if not isinstance(sid, str) or not sid or not isinstance(trace, str) or not trace:
        raise ValueError("Every original attempt needs session_id and trace_id")
    for number, event in enumerate(events, 1):
        if (not isinstance(event, dict) or event.get("session_id") != sid
                or event.get("trace_id") != trace or event.get("run_id") != trace
                or type(event.get("seq")) is not int or event["seq"] != number):
            raise ValueError("Events must be complete, ordered and match session/trace")
    finals = [event for event in events if event.get("type") == "result"]
    if len(finals) != 1 or finals[0] is not events[-1]:
        raise ValueError("Expected exactly one terminal result at the end")
    final = finals[0]
    if (type(final.get("tokens")) is not int or final["tokens"] < 0
            or type(record.get("tokens")) is not int or final["tokens"] != record["tokens"]):
        raise ValueError("Terminal tokens do not match the original attempt")
    if final.get("outcome") not in ("success", "error", "cancelled"):
        raise ValueError("Unrecognized terminal outcome")
    if final.get("outcome") == "success" and final.get("error"):
        raise ValueError("Success cannot contain a terminal error")
    if final.get("outcome") != "success" and record["pass"]:
        raise ValueError("Original successful verdict contradicts terminal outcome")
    models = [{"provider": event.get("provider"), "model": event.get("model")}
              for event in events if event.get("type") == "model"]
    if any(model != record.get("model") for model in models) or (not models and record.get("model")):
        raise ValueError("Observed model provenance differs from the original attempt")
    return final


def workspace_path(root, value, task):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Invalid workspace path")
    path = Path(value)
    if ".." in path.parts or not re.fullmatch(r"baf-" + re.escape(task.replace(".", "-")) + r"-[0-9a-f]{10}", path.name):
        raise ValueError("Workspace must name the task's original fixture directory")
    candidate = root / path.name
    # Accept published basenames or the original actual absolute/relative path;
    # never silently reinterpret an outside path as an inside basename.
    if len(path.parts) > 1 and path.absolute().parent.resolve() != root:
        raise ValueError("Workspace path is outside the supplied root")
    if candidate.is_symlink() or not candidate.is_dir() or candidate.resolve() != candidate:
        raise ValueError("Workspace must be an existing direct non-symlink child")
    return candidate


def snapshot_files(case, workspace):
    names = set(case["fixture"])
    if case.get("source_file"):
        names.add(case["source_file"])
    if case["id"] == "C3":
        names.add("tests/test_duration.py")
    if case["id"] == "B5.4":
        names.add("answer.json")
    files = {}
    for name in sorted(names):
        try:
            data = read_file(workspace, name)
            files[name] = {"utf8": data.decode("utf-8"), "sha256": digest(data), "bytes": len(data)}
        except (OSError, ValueError, UnicodeError) as exc:
            # Missing/unsafe artifacts are evidence of failure, not empty files.
            files[name] = {"read_error": type(exc).__name__}
    return files


def grade_snapshot(case, files, events, grader, checker):
    with tempfile.TemporaryDirectory(prefix="baf-regrade-") as directory:
        root = Path(directory)
        for name, entry in files.items():
            if "utf8" not in entry:
                continue
            path = root / name
            # Fixture/source names come from the trusted registry, not model data.
            if not path.is_relative_to(root) or ".." in Path(name).parts:
                raise ValueError("Invalid registered artifact name")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(entry["utf8"].encode("utf-8"))
        result = checker(case, root, events, grader)
        if not isinstance(result, dict) or type(result.get("pass")) is not bool or not isinstance(result.get("reason"), str):
            raise ValueError("Checker returned an invalid verdict")
        if any("read_error" in entry for entry in files.values()):
            result = {**result, "pass": False, "reason": "Required artifact was missing, unsafe or not UTF-8"}
        return result


def regrade(records, event_map, workspace_root, grader, checker_revision, *, registry=None,
            checker=check, repeats=3):
    """Pure orchestration boundary: tests inject only the checker and evaluator."""
    registry = {case["id"]: case for case in (cases() if registry is None else registry)}
    if not AFFECTED <= registry.keys() or type(repeats) is not int or repeats < 1:
        raise ValueError("Registry must contain every affected task and repeats must be positive")
    validate_records(records, sorted(registry), repeats)
    if len({record["pair_label"] for record in records}) != 1:
        raise ValueError("Regrade one frozen pair at a time")
    expected = {(task, repeat) for task in registry for repeat in range(1, repeats + 1)}
    if {(record["task"], record["repeat"]) for record in records} != expected:
        raise ValueError("Original campaign is incomplete; do not cherry-pick attempts")
    if not isinstance(event_map, dict):
        raise ValueError("Events must be a session-id to full-event-list mapping")
    root = Path(workspace_root).resolve(strict=True)
    validated = {}
    sessions = set()
    # Validate all observations before running even one hidden checker.
    for record in records:
        sid = record.get("session_id")
        if sid in sessions:
            raise ValueError("A campaign attempt must have its own session")
        sessions.add(sid)
        validated[sid] = final_event(record, event_map.get(sid))
        if "original_verdict" in record or "regrade_verdict" in record:
            raise ValueError("Input is already regraded; use the original raw campaign")
    if set(event_map) != sessions:
        raise ValueError("Event map must cover exactly the original campaign sessions")
    paths = {record["session_id"]: workspace_path(root, record.get("workspace"), record["task"])
             for record in records if record["task"] in AFFECTED}
    corrected, snapshots, changed = [], [], []
    changed_fields = {}
    for record in records:
        row = copy.deepcopy(record)
        if record["task"] not in AFFECTED:
            corrected.append(row)
            continue
        sid = record["session_id"]
        case, workspace, events = registry[record["task"]], paths[sid], event_map[sid]
        files = snapshot_files(case, workspace)
        start = time.perf_counter_ns()
        verdict = grade_snapshot(case, files, events, grader, checker)
        elapsed = round((time.perf_counter_ns() - start) / 1_000_000, 3)
        if snapshot_files(case, workspace) != files:
            raise ValueError("Original workspace changed during regrading; refuse inconsistent evidence")
        final = validated[sid]
        runtime_failed = final["outcome"] != "success" or bool(record.get("error_kind"))
        row["original_verdict"] = {key: copy.deepcopy(record[key]) for key in VERDICT_KEYS if key in record}
        row["regrade_verdict"] = verdict
        row["regrade_check_ms"] = elapsed
        row["regrade_checker_revision"] = checker_revision
        row["pass"] = bool(verdict["pass"] and not runtime_failed)
        row["reason"] = record["reason"] if runtime_failed else verdict["reason"]
        row["regrade_runtime_failure_preserved"] = runtime_failed
        fields = sorted(key for key in set(row) | set(record) if key not in record or row[key] != record[key])
        identity = {"task": record["task"], "repeat": record["repeat"], "session_id": sid}
        changed_fields[sid] = fields
        if row["pass"] != record["pass"] or row["reason"] != record["reason"]:
            changed.append({**identity, "original": {"pass": record["pass"], "reason": record["reason"]},
                            "corrected": {"pass": row["pass"], "reason": row["reason"]}})
        snapshots.append({**identity, "workspace": workspace.name, "files": files,
                          "events_sha256": digest(json_bytes(events))})
        corrected.append(row)
    audit = {"source_revision": SOURCE_REVISION, "checker_revision": checker_revision,
             "affected_tasks": sorted(AFFECTED), "records": len(records), "regraded": len(snapshots),
             "untouched": len(records) - len(snapshots), "repeats": repeats,
             "model_calls": 0, "original_passed": sum(r["pass"] for r in records),
             "corrected_passed": sum(r["pass"] for r in corrected),
             "changed_verdicts": changed, "changed_record_fields": changed_fields,
             "changed_record_field_count": sum(len(fields) for fields in changed_fields.values()),
             "semantics": "Only pass/reason change among original fields. Original duration/generation/tokens/model/IDs and legacy check fields are immutable; regrade_verdict and regrade_check_ms hold the new checker evidence. Runtime error attempts remain failed. UTF-8 snapshots are data only."}
    return corrected, audit, snapshots


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--workspace-root", default="workspaces")
    parser.add_argument("--output", required=True)
    parser.add_argument("--audit", help="Default: OUTPUT.audit.json")
    parser.add_argument("--snapshots", help="Default: OUTPUT.snapshots.json (required evidence, always saved)")
    parser.add_argument("--checker-revision", required=True, help="Commit ID or explicit working-tree correction label")
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    source, events_path, output = Path(args.input), Path(args.events), Path(args.output)
    audit_path = Path(args.audit or str(output) + ".audit.json")
    snapshots_path = Path(args.snapshots or str(output) + ".snapshots.json")
    destinations = [output, audit_path, snapshots_path]
    inputs = {source.resolve(), events_path.resolve()}
    if (len({path.resolve() for path in destinations}) != 3
            or any(path.exists() or path.is_symlink() or path.resolve() in inputs for path in destinations)):
        parser.error("Output, audit and snapshot paths must be distinct new files; originals cannot be overwritten")
    source_data, event_data = source.read_bytes(), events_path.read_bytes()
    records = load_records([source])
    event_map = json.loads(event_data, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    repo = Path(__file__).resolve().parents[1]
    checker_paths = checker_files(repo)
    checker_hashes = {name: digest((repo / name).read_bytes()) for name in checker_paths}
    grader = FunctionEvaluator()
    grader.engine.ping()  # Fail before publishing verdicts if the Docker grader is unavailable.
    corrected, audit, snapshots = regrade(records, event_map, args.workspace_root,
                                          grader, args.checker_revision, repeats=args.repeats)
    if source.read_bytes() != source_data or events_path.read_bytes() != event_data:
        raise ValueError("Input campaign/events changed during regrading")
    if checker_hashes != {name: digest((repo / name).read_bytes()) for name in checker_files(repo)}:
        raise ValueError("Checker source changed during regrading")
    audit["checker_source_sha256"] = checker_hashes
    audit["checker_git_head"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    audit["checker_git_status"] = subprocess.check_output(
        ["git", "status", "--porcelain", "--", *checker_paths], cwd=repo, text=True).splitlines()
    output_data = b"".join((json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8") for row in corrected)
    snapshot_data = json_bytes({"source_revision": SOURCE_REVISION, "attempts": snapshots})
    audit.update(input_sha256=digest(source_data), events_sha256=digest(event_data),
                 corrected_sha256=digest(output_data), snapshots_sha256=digest(snapshot_data))
    for path, data in ((snapshots_path, snapshot_data), (audit_path, json_bytes(audit)), (output, output_data)):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as file:
            file.write(data)
    print(f"Regraded {audit['regraded']}/{audit['records']} attempts; {audit['untouched']} unchanged; "
          f"passes {audit['original_passed']} -> {audit['corrected_passed']}; model calls: 0")


if __name__ == "__main__":
    main()
