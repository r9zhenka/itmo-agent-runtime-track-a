"""Audit raw benchmark JSONL and produce a provenance-aware JSON/Markdown matrix.

Failures and missing attempts are never dropped. Replay is infrastructure evidence,
not model-quality evidence, and cannot be mixed into a live-model campaign.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import statistics

from baf.json_output import invalid_constant, unique_object
from scripts.measure_common import environment, save_report, summarize

UNCERTAIN_ERRORS = {"model", "timeout", "transport", "unknown"}
SUPPORTED_PROVIDERS = {"live", "synthetic-replay", "recorded-replay"}


def load_records(paths):
    records = []
    for path in paths:
        with Path(path).open(encoding="utf-8") as file:
            line_number = 0
            while True:
                line = file.readline(1_048_577)
                if not line:
                    break
                line_number += 1
                if len(line) > 1_048_576:
                    raise ValueError(f"{path}:{line_number}: oversized JSONL record")
                if not line.strip():
                    continue
                try:
                    item = json.loads(line, object_pairs_hook=unique_object, parse_constant=invalid_constant)
                except (ValueError, RecursionError) as exc:
                    raise ValueError(f"{path}:{line_number}: malformed JSONL record") from exc
                if not isinstance(item, dict):
                    raise ValueError(f"{path}:{line_number}: expected an object")
                records.append(item)
    return records


def natural_key(identifier):
    return [(0, int(part)) if part.isdigit() else (1, part) for part in re.split(r"(\d+)", identifier)]


def provenance(record):
    model = record.get("model")
    return model.get("provider") if isinstance(model, dict) else None


def usage_uncertain(record):
    return (record.get("usage_partial") is True or provenance(record) is None or "tokens" not in record
            or record.get("error_kind") in UNCERTAIN_ERRORS
            or (provenance(record) == "live" and record.get("tokens") == 0))


def validate_records(records, tasks, repeats, pairs=None):
    seen, providers, models = set(), set(), {}
    for record in records:
        task, pair, repeat = record.get("task"), record.get("pair_label"), record.get("repeat")
        if not isinstance(task, str) or task not in tasks:
            raise ValueError(f"Unexpected or unregistered task: {task!r}")
        if not isinstance(pair, str) or not pair.strip():
            raise ValueError("Every record needs a nonempty pair_label")
        if pairs is not None and pair not in pairs:
            raise ValueError("Unexpected pair label: " + pair)
        if type(repeat) is not int or not 1 <= repeat <= repeats:
            raise ValueError(f"Invalid repeat for {task}: {repeat!r}")
        if type(record.get("pass")) is not bool:
            raise ValueError("Each attempt needs a boolean pass verdict")
        identity = (pair, task, repeat)
        if identity in seen:
            raise ValueError(f"Duplicate attempt {identity!r}; do not overwrite or cherry-pick reruns")
        seen.add(identity)
        provider = provenance(record)
        if provider is None:
            if record["pass"] or record.get("quality_evaluation"):
                raise ValueError("Unverified provenance can only describe failed, non-quality-marked attempts")
        elif provider not in SUPPORTED_PROVIDERS:
            raise ValueError("Unsupported provider provenance: " + str(provider))
        else:
            providers.add(provider)
            model = record["model"].get("model")
            if not isinstance(model, str) or not model:
                raise ValueError("Verified provider records need an exact model ID")
            models.setdefault(pair, set()).add((provider, model))
            if len(models[pair]) != 1:
                raise ValueError("Model/provider changed inside pair: " + pair)
            if provider == "live" and record.get("quality_evaluation") is not True:
                raise ValueError("Live provenance contradicts the quality_evaluation marker")
            if provider in ("synthetic-replay", "recorded-replay") and record.get("quality_evaluation"):
                raise ValueError("Replay cannot be model-quality evidence")
        if "tokens" in record and (type(record["tokens"]) is not int or record["tokens"] < 0):
            raise ValueError("Reported token usage must be a nonnegative integer")
        if "usage_partial" in record and type(record["usage_partial"]) is not bool:
            raise ValueError("usage_partial must be a boolean")
        for field in ("duration_ms", "generation_ms"):
            if field in record and (type(record[field]) not in (int, float)
                                    or not math.isfinite(record[field]) or record[field] < 0):
                raise ValueError(field + " must be a finite nonnegative number")
        if record.get("error_kind") is not None and not isinstance(record["error_kind"], str):
            raise ValueError("error_kind must be a string or null")
    if len(providers) > 1:
        raise ValueError("Mixed live/replay records cannot form a model-quality comparison")
    return next(iter(providers), "unverified"), models


def sample_stats(values):
    return summarize(values) if values else None


def aggregate(records, expected):
    count = len(records)
    passed = sum(record["pass"] for record in records)
    uncertain = sum(usage_uncertain(record) for record in records)
    error_counts = Counter(record.get("error_kind") or ("checker_failure" if provenance(record) else "unclassified_failure")
                           for record in records if not record["pass"])
    return {
        "expected_runs": expected, "observed_runs": count, "passed": passed, "failed": count - passed,
        "missing_runs": expected - count, "complete": count == expected,
        "pass_rate_observed": passed / count if count else None,
        "pass_rate_expected_lower_bound": passed / expected if expected else None,
        "reported_tokens_total": sum(record.get("tokens", 0) for record in records),
        "usage_unknown_runs": uncertain, "token_usage_complete": uncertain == 0 and count == expected,
        "reported_tokens_per_run": sample_stats([record["tokens"] for record in records if "tokens" in record]),
        "duration_ms": sample_stats([record["duration_ms"] for record in records if "duration_ms" in record]),
        "generation_ms": sample_stats([record["generation_ms"] for record in records if "generation_ms" in record]),
        "missing_duration_runs": sum("duration_ms" not in record for record in records),
        "outcomes": {"passed": passed, "failed": count - passed, "not_run": expected - count},
        "failure_kinds": dict(sorted(error_counts.items())),
    }


def group_stats(records, tasks, repeats):
    result = aggregate(records, len(tasks) * repeats)
    by_repeat = []
    for repeat in range(1, repeats + 1):
        part = aggregate([record for record in records if record["repeat"] == repeat], len(tasks))
        by_repeat.append({"repeat": repeat, **part})
    rates = [item["pass_rate_observed"] for item in by_repeat if item["complete"]]
    result["repeat_results"] = by_repeat
    result["complete_repeat_rate_spread"] = ({**summarize(rates), "mean": statistics.mean(rates),
                                               "population_stddev": statistics.pstdev(rates),
                                               "range": max(rates) - min(rates)} if rates else None)
    return result


def summarize_campaign(records, expected_tasks, repeats=3, expected_pairs=None):
    tasks = list(expected_tasks)
    if not tasks or any(not isinstance(task, str) or not task for task in tasks) or len(tasks) != len(set(tasks)):
        raise ValueError("Expected tasks must be unique nonempty identifiers")
    tasks.sort(key=natural_key)
    if type(repeats) is not int or repeats < 1:
        raise ValueError("Expected repeats must be a positive integer")
    if expected_pairs is not None and (not expected_pairs
                                      or any(not isinstance(pair, str) or not pair.strip() for pair in expected_pairs)
                                      or len(expected_pairs) != len(set(expected_pairs))):
        raise ValueError("Expected pair labels must be nonempty and unique")
    mode, models = validate_records(records, set(tasks), repeats, expected_pairs)
    pairs = sorted(expected_pairs if expected_pairs is not None else {record["pair_label"] for record in records})
    groups = sorted({task.split(".")[0] for task in tasks}, key=natural_key)
    pair_reports = []
    for pair in pairs:
        attempts = [record for record in records if record["pair_label"] == pair]
        known_model = next(iter(models.get(pair, set())), (None, None))
        quality = known_model[0] == "live"
        report = {"pair_label": pair, "provider": known_model[0] or "unverified", "model": known_model[1],
                  "quality_evaluation": quality, **group_stats(attempts, tasks, repeats), "tasks": {}, "baf": {}}
        identities = {(record["task"], record["repeat"]) for record in attempts}
        report["missing_attempts"] = [{"task": task, "repeat": repeat} for task in tasks
                                      for repeat in range(1, repeats + 1) if (task, repeat) not in identities]
        for task in tasks:
            report["tasks"][task] = group_stats([record for record in attempts if record["task"] == task], [task], repeats)
        for group in groups:
            members = [task for task in tasks if task.split(".")[0] == group]
            report["baf"][group] = {"tasks": members, **group_stats(
                [record for record in attempts if record["task"] in members], members, repeats)}
        report["failures"] = [{"task": record["task"], "repeat": record["repeat"],
                               "error_kind": record.get("error_kind"), "reason": str(record.get("reason", "")),
                               "reported_tokens": record.get("tokens"), "usage_unknown": usage_uncertain(record),
                               "duration_ms": record.get("duration_ms")}
                              for record in attempts if not record["pass"]]
        pair_reports.append(report)
    complete = bool(pair_reports) and all(pair["complete"] for pair in pair_reports)
    quality = bool(pair_reports) and all(pair["quality_evaluation"] for pair in pair_reports)
    return {"schema_version": 1, "generated": environment(), "provenance": mode,
            "quality_evaluation": quality, "complete": complete,
            "status": "complete" if complete else "partial" if records else "empty",
            "expected": {"tasks": tasks, "task_count": len(tasks), "repeats": repeats,
                         "pair_labels": pairs, "runs_per_pair": len(tasks) * repeats},
            "pair_count": len(pairs), "observed_runs": len(records),
            "reported_tokens_total": sum(record.get("tokens", 0) for record in records),
            "usage_unknown_runs": sum(usage_uncertain(record) for record in records),
            "method": {"p95": "nearest rank", "spread": "population standard deviation of complete per-repeat group pass rates",
                       "missing": "Not counted as observed failures; shown separately and included in expected-denominator lower bounds",
                       "tokens": "Reported totals are lower bounds when failed calls or missing metadata leave usage unknown",
                       "comparability": "One model ID per pair; same expected tasks/repeats; environment equivalence must be documented separately"},
            "pairs": pair_reports}


def escape(value):
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def percent(value):
    return "—" if value is None else f"{100 * value:.1f}%"


def timing(stats):
    return "—" if stats is None else f"{stats['median'] / 1000:.3f} / {stats['p95'] / 1000:.3f}"


def markdown_report(report):
    lines = ["# Benchmark campaign", "",
             f"Status: **{report['status']}**. Provenance: **{report['provenance']}**.", "",
             ("This contains live-model quality evidence; partial coverage and failures remain visible."
              if report["quality_evaluation"] else "This is not a verified live-model quality campaign; replay/unverified results cannot establish model quality."),
             "", f"Expected: {report['expected']['task_count']} tasks × {report['expected']['repeats']} repeats per pair. "
             f"Observed: {report['observed_runs']} attempts across {report['pair_count']} pair(s).", "",
             f"Reported tokens: **{report['reported_tokens_total']}**. Usage uncertain for **{report['usage_unknown_runs']}** attempts; "
             "reported totals do not include unreported provider charges.", "",
             "## BAF × pair", "",
             "Cells show passed/observed, observed success rate, and coverage observed/expected. Missing attempts are not silently dropped.", ""]
    pairs = report["pairs"]
    if pairs:
        groups = list(pairs[0]["baf"])
        lines.extend(["| BAF | " + " | ".join(escape(pair["pair_label"]) for pair in pairs) + " |",
                      "|---|" + "---|" * len(pairs)])
        for group in groups:
            cells = []
            for pair in pairs:
                cell = pair["baf"][group]
                cells.append(f"{cell['passed']}/{cell['observed_runs']} ({percent(cell['pass_rate_observed'])}); "
                             f"coverage {cell['observed_runs']}/{cell['expected_runs']}")
            lines.append("| " + escape(group) + " | " + " | ".join(cells) + " |")
    else:
        lines.append("No attempts or expected pair labels were supplied.")
    for pair in pairs:
        lines.extend(["", "## " + escape(pair["pair_label"]), "",
                      f"Provider: `{escape(pair['provider'])}`; model: `{escape(pair['model'])}`. "
                      f"Passed {pair['passed']}/{pair['observed_runs']}; missing {pair['missing_runs']}/{pair['expected_runs']}.", "",
                      "| Group | Pass rate | Repeat rates (coverage) | Spread σ / range | Reported tokens | Unknown usage runs | Duration median / p95, s |",
                      "|---|---|---|---|---:|---:|---|"])
        for group, value in pair["baf"].items():
            repeat_rates = "; ".join(f"#{item['repeat']}: {percent(item['pass_rate_observed'])} ({item['observed_runs']}/{item['expected_runs']})"
                                     for item in value["repeat_results"])
            spread = value["complete_repeat_rate_spread"]
            dispersion = (f"{100 * spread['population_stddev']:.1f} / {100 * spread['range']:.1f} pp; n={spread['n']}"
                          if spread else "—")
            lines.append(f"| {escape(group)} | {percent(value['pass_rate_observed'])} | {repeat_rates} | {dispersion} | "
                         f"{value['reported_tokens_total']} | {value['usage_unknown_runs']} | {timing(value['duration_ms'])} |")
        lines.extend(["", "### Per-task results", "",
                      "| Task | Passed / observed / expected | Failed | Missing | Reported tokens | Duration median / p95, s |",
                      "|---|---|---:|---:|---:|---|"])
        for task, value in pair["tasks"].items():
            lines.append(f"| {escape(task)} | {value['passed']} / {value['observed_runs']} / {value['expected_runs']} | "
                         f"{value['failed']} | {value['missing_runs']} | {value['reported_tokens_total']} | {timing(value['duration_ms'])} |")
        if pair["failures"]:
            lines.extend(["", "### Failed attempts", "", "| Task | Repeat | Error kind | Reason |", "|---|---:|---|---|"])
            for failure in pair["failures"]:
                lines.append(f"| {escape(failure['task'])} | {failure['repeat']} | {escape(failure['error_kind'] or 'checker/unclassified')} | "
                             f"{escape(failure['reason'])} |")
    lines.extend(["", "p95 uses nearest rank. Repeat-rate spread uses complete repeats only; its sample count is shown. "
                  "Timing summaries include failed attempts when timings were recorded. Raw JSON and the JSON summary retain missing timings and unknown token usage.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", nargs="+", required=True, help="One or more raw benchmark JSONL files")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--expected-task", action="append", help="Override registered-task expectation, e.g. for a smoke campaign")
    parser.add_argument("--pair", action="append", help="Expected pair label, including a pair that has no completed attempts yet")
    parser.add_argument("--output", default="results/benchmark-summary.json")
    parser.add_argument("--markdown", default="results/benchmark-summary.md")
    args = parser.parse_args()
    try:
        from baf.cases import cases
        tasks = args.expected_task or [case["id"] for case in cases()]
        report = summarize_campaign(load_records(args.input), tasks, args.repeats, args.pair)
        report["inputs"] = [str(Path(path)) for path in args.input]
        save_report(args.output, report)
        target = Path(args.markdown)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown_report(report))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f"{report['status']}: {report['observed_runs']} attempts, {report['reported_tokens_total']} reported tokens; "
          f"JSON: {args.output}; Markdown: {args.markdown}")


if __name__ == "__main__":
    main()
