"""Independent B8 grading: trusted input arithmetic and curated text annotations.

Annotations stay outside benchmark workspaces. No replay code or agent-edited
inputs are used to compute expectations, and submitted code is never executed.
"""
import csv
import io
import json
from datetime import date
from decimal import Decimal

from .json_output import read_answer, require_equal


def sales_answer(fixture):
    request = json.loads(fixture["request.json"])
    start, end = date.fromisoformat(request["start"]), date.fromisoformat(request["end"])
    sources = []
    for filename in sorted(request["files"]):
        amounts = [Decimal(row["amount"]) for row in csv.DictReader(io.StringIO(fixture[filename]))
                   if start <= date.fromisoformat(row["date"]) < end]
        sources.append({"file": filename, "total_kopecks": int(sum(amounts, Decimal(0)) * 100),
                        "row_count": len(amounts)})
    return {"quarter": request["quarter"], "currency": "RUB",
            "total_kopecks": sum(item["total_kopecks"] for item in sources), "sources": sources}


def meeting_answer():
    # Manually annotated accepted/reaffirmed sections, independent of replay.
    # A prose parser here would turn the oracle into another fallible NLP system.
    annotations = [
        ("D101", "Анна", "2026-10-20", [("01", "P1"), ("04", "P1")]),
        ("D102", "Борис", None, [("03", "P1")]),
        ("D103", None, "2026-10-31", [("05", "P1")]),
        ("D104", "Ирина", "2026-11-01", [("07", "P1")]),
        ("D105", None, None, [("08", "P1")]),
        ("D106", "Лев", "2026-11-05", [("10", "P2")]),
    ]
    return {"decisions": [
        {"decision_id": identifier, "owner": owner, "due_date": due,
         "sources": [{"file": f"meetings/{number}.md", "section": section} for number, section in citations]}
        for identifier, owner, due, citations in annotations]}


def regulation_answer(fixture):
    as_of = json.loads(fixture["request.json"])["as_of"]
    versions = json.loads(fixture["catalog.json"])["versions"]
    eligible = [version for version in versions if version["status"] == "approved"
                and date.fromisoformat(version["effective_from"]) <= date.fromisoformat(as_of)]
    selected = max(eligible, key=lambda version: date.fromisoformat(version["effective_from"]))
    other, = [version for version in versions if version["version"] != selected["version"]]
    # Independently annotated clause values from the two supplied documents.
    clauses = {"v1": {"C1": 30, "C2": 48, "C3": "EU"},
               "v2": {"C1": 90, "C2": 24, "C3": "EU"}}
    units = {"C1": "days", "C2": "hours", "C3": "region"}
    current, previous = clauses[selected["version"]], clauses[other["version"]]
    return {
        "as_of": as_of, "version": selected["version"], "source": selected["file"],
        "values": [{"clause_id": key, "value": value, "unit": units[key]}
                   for key, value in sorted(current.items())],
        "differences": [{"clause_id": key, "unit": units[key], "selected_value": value,
                         "other_value": previous[key], "selected_source": selected["file"],
                         "other_source": other["file"]}
                        for key, value in sorted(current.items()) if value != previous[key]],
    }


def check(case, workspace):
    try:
        actual = read_answer(workspace)
        identifier = case["id"]
        if identifier == "B8.1":
            expected = sales_answer(case["fixture"])
        elif identifier == "B8.2":
            expected = meeting_answer()
        elif identifier == "B8.3":
            expected = regulation_answer(case["fixture"])
        else:
            raise ValueError("Unknown synthesis task: " + identifier)
        require_equal(actual, expected)
        return {"pass": True, "reason": "ok"}
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        return {"pass": False, "reason": str(exc)}
