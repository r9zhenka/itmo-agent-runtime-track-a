"""Independent data-only B7 oracles. Never execute agent-supplied code."""
import json
from datetime import datetime, timedelta
from itertools import combinations
from .json_output import read_answer, require_equal


def transfer_answer(data):
    ready = datetime.fromisoformat(data["arrival"]) + timedelta(minutes=data["walk_minutes"])
    closes = datetime.fromisoformat(data["departure"]) - timedelta(minutes=data["boarding_closes_minutes_before"])
    return {"can_transfer": ready <= closes, "ready_at": ready.isoformat(timespec="minutes"),
            "boarding_closes_at": closes.isoformat(timespec="minutes"),
            "margin_minutes": (closes - ready) // timedelta(minutes=1)}


def policy_answer(data):
    rules = {rule["id"]: rule for rule in data["rules"]}
    decisions = []
    for role in sorted(data["roles"]):
        pending, visited, identifiers = [role], set(), set()
        while pending:
            current = pending.pop()
            if current in visited:
                continue
            visited.add(current)
            definition = data["roles"][current]
            identifiers.update(definition["rules"])
            pending.extend(definition["inherits"])
        matched = [rules[key] for key in sorted(identifiers)
                   if all(rules[key][field] == data["query"][field] for field in ("action", "resource"))]
        allows = [rule["id"] for rule in matched if rule["effect"] == "allow"]
        denies = [rule["id"] for rule in matched if rule["effect"] == "deny"]
        decisions.append({"role": role, "allowed": bool(allows) and not denies,
                          "allow_rules": allows, "deny_rules": denies})
    return {"allowed_roles": [item["role"] for item in decisions if item["allowed"]], "decisions": decisions}


def conflict_answer(data):
    conflicts = []
    for left, right in combinations(sorted(data["rules"], key=lambda rule: rule["id"]), 2):
        if (left["action"], left["resource"]) != (right["action"], right["resource"]):
            continue
        if {left["effect"], right["effect"]} != {"allow", "deny"}:
            continue
        contexts = sorted(context["id"] for context in data["contexts"]
                          if all(key in context["facts"] and context["facts"][key] == value
                                 for rule in (left, right) for key, value in rule["when"].items()))
        if contexts:
            conflicts.append({"rules": [left["id"], right["id"]], "contexts": contexts})
    return {"conflicts": conflicts}


def check(case, workspace):
    try:
        actual = read_answer(workspace)
        # Use the original in-memory fixture, never possibly edited workspace inputs.
        data = json.loads(case["fixture"][case["input_file"]])
        oracle = {"B7.1": transfer_answer, "B7.2": policy_answer, "B7.3": conflict_answer}[case["id"]]
        expected = oracle(data)
        require_equal(actual, expected)
        return {"pass": True, "reason": "ok"}
    except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        return {"pass": False, "reason": str(exc)}
