"""Small, explicit statistical helpers for reproducible infrastructure measurements."""
import datetime
import json
import math
import platform
import statistics
from pathlib import Path


def summarize(values):
    values = list(values)
    if not values or any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
        raise ValueError("Measurements must be nonempty finite numeric samples")
    ordered = sorted(values)
    return {"n": len(values), "median": statistics.median(values),
            "p95": ordered[math.ceil(0.95 * len(values)) - 1],
            "min": ordered[0], "max": ordered[-1], "p95_method": "nearest rank"}


def summarize_records(records, columns):
    return {column: summarize(record[column] for record in records) for column in columns}


def environment():
    return {"python": platform.python_version(), "system": platform.system(),
            "kernel": platform.release(), "architecture": platform.machine(),
            "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()}


def save_report(path, report):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
