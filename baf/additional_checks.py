"""Data-only oracles for added tasks; submitted Python runs only in FunctionEvaluator."""
import ast
import csv
import io
import json

from .artifacts import read_file
from .json_output import read_answer, require_equal, unique_object, invalid_constant


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def preserve(case, workspace, except_files=()):
    for filename, original in case["fixture"].items():
        if filename not in except_files:
            expected = original.encode("utf-8") if isinstance(original, str) else original
            require(read_file(workspace, filename) == expected, "Unexpected modification: " + filename)


def command_observed(events, *, code=0, stdout=None, stderr_contains=None):
    for event in events:
        result = event.get("result", {})
        if event.get("type") != "tool_result" or event.get("tool") != "RunCommand":
            continue
        if result.get("exit_code") != code:
            continue
        if code == 0 and result.get("error"):
            continue
        if stdout is not None and result.get("stdout", "").strip() != stdout:
            continue
        if stderr_contains is not None and stderr_contains not in result.get("stderr", ""):
            continue
        return True
    return False


def plugin_matches(fixture):
    matches = []
    for filename, text in fixture.items():
        if not filename.startswith("plugins/") or not filename.endswith(".py"):
            continue
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name)
                        and decorator.func.id == "register" and len(decorator.args) == 1
                        and isinstance(decorator.args[0], ast.Constant) and decorator.args[0].value == "invoice"):
                    matches.append({"file": filename, "function": node.name})
                    break
    return {"matches": sorted(matches, key=lambda item: (item["file"], item["function"]))}


def maintenance_answer(fixture):
    data = json.loads(fixture["maintenance.json"])
    def minute(text):
        hour, value = map(int, text.split(":"))
        return hour * 60 + value
    candidates = []
    for candidate in data["candidates"]:
        start, end = minute(candidate["start"]), minute(candidate["end"])
        if end - start < data["required_minutes"]:
            continue
        if any(start < minute(right) and minute(left) < end for left, right in data["blackouts"]):
            continue
        candidates.append((start, candidate["id"]))
    selected = min(candidates)[1] if candidates else None
    return {"selected": selected, "rejected": sorted(c["id"] for c in data["candidates"] if c["id"] != selected)}


def stock_answer(fixture):
    recalled = set(json.loads(fixture["recalls.json"])["skus"])
    stock = {}
    for filename in sorted(fixture):
        if not filename.startswith("warehouse/") or not filename.endswith(".json"):
            continue
        for row in json.loads(fixture[filename]):
            if row["sku"] in recalled:
                continue
            item = stock.setdefault(row["sku"], {"sku": row["sku"], "available": 0, "sources": []})
            item["available"] += row["on_hand"] - row["reserved"]
            if filename not in item["sources"]:
                item["sources"].append(filename)
    return {"stock": [stock[sku] for sku in sorted(stock)]}


def department_answer(fixture):
    manifests = [json.loads(text) for filename, text in fixture.items() if filename.endswith("manifest.json")]
    manifest, = [item for item in manifests if item["active"]]
    budgets = json.loads(fixture["policy.json"])["budget_cents"]
    records = {name: {"name": name, "spent_cents": 0, "budget_cents": amount,
                      "over_budget": False, "sources": []} for name, amount in budgets.items()}
    for filename in sorted(manifest["files"]):
        for row in csv.DictReader(io.StringIO(fixture[filename])):
            if not "2026-10-01" <= row["date"] < "2026-11-01":
                continue
            record = records[row["department"]]
            record["spent_cents"] += int(row["amount_cents"])
            if filename not in record["sources"]:
                record["sources"].append(filename)
    for record in records.values():
        record["over_budget"] = record["spent_cents"] > record["budget_cents"]
    return {"total_cents": sum(record["spent_cents"] for record in records.values()),
            "departments": [records[name] for name in sorted(records)]}


def incident_notice(fixture):
    latest = {}
    for filename in sorted(fixture):
        if not filename.startswith("incidents/") or not filename.endswith(".json"):
            continue
        for item in json.loads(fixture[filename]):
            if item["id"] not in latest or item["updated_at"] > latest[item["id"]]["updated_at"]:
                latest[item["id"]] = item
    chosen = [item for _, item in sorted(latest.items()) if item["severity"] == "critical" and item["status"] == "open"]
    rows = [f"{item['id']}: {item['service']} — investigating." for item in chosen]
    return "Service notice\n" + "\n".join(rows or ["No active critical incidents."]) + "\n"


def duration_integration(workspace, events):
    main = ast.parse(read_file(workspace, "main.py").decode("utf-8"))
    expected_main = ast.parse("import sys\nfrom utils.duration import parse_duration\nprint(parse_duration(sys.argv[1]))\n")
    require(ast.dump(main) == ast.dump(expected_main), "main.py must contain the three specified integration statements")
    test = ast.parse(read_file(workspace, "tests/test_duration.py").decode("utf-8"))
    require(any(isinstance(node, ast.ImportFrom) and node.module == "utils.duration"
                and any(alias.name == "parse_duration" and alias.asname is None for alias in node.names)
                for node in ast.walk(test)), "Tests must import the real utility")
    covered = set()
    for node in ast.walk(test):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or not node.args:
            continue
        call = node.args[0]
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "parse_duration"
                and len(call.args) == 1 and isinstance(call.args[0], ast.Constant)):
            continue
        if node.func.attr == "assertIsNone":
            covered.add((call.args[0].value, None))
        elif node.func.attr == "assertEqual" and len(node.args) == 2 and isinstance(node.args[1], ast.Constant):
            covered.add((call.args[0].value, node.args[1].value))
    require({("1h2m3s", 3723), ("0s", 0), ("60m", None)} <= covered,
            "Add direct unittest assertions for all three specified public examples")
    require(command_observed(events, stderr_contains="Ran 3 tests"), "Three public tests were not observed passing")
    require(command_observed(events, stdout="3723"), "CLI result was not observed")


def check(case, workspace, events, code_evaluator=None):
    """Fail closed on missing/malformed artifacts; use only original fixture inputs."""
    try:
        identifier, fixture = case["id"], case["fixture"]
        if identifier == "B1.4":
            source = json.loads(fixture["invoices/current.json"])
            require_equal(read_answer(workspace), {"postal_code": source["customer"]["postal_code"], "reference": source["payment"]["reference"]})
        elif identifier == "B2.4":
            require_equal(read_answer(workspace), plugin_matches(fixture))
        elif identifier == "B3.4":
            raw = read_file(workspace, "export.jsonl").decode("utf-8")
            require(raw.endswith("\n"), "JSONL must end with a newline")
            actual = [json.loads(line, object_pairs_hook=unique_object, parse_constant=invalid_constant) for line in raw.splitlines()]
            expected = [{"id": row["id"], "text": row["text"]} for row in sorted(json.loads(fixture["records.json"]), key=lambda row: row["id"])]
            require_equal(actual, expected)
        elif identifier == "B4.4":
            expected = fixture["service.ini"].replace(b"[production]\r\nport = 8000", b"[production]\r\nport = 9000")
            require(read_file(workspace, "service.ini") == expected, "Unexpected INI byte changes")
        elif identifier == "B5.4":
            preserve(case, workspace)
            require(command_observed(events, code=3, stderr_contains="no automatic retry"), "Probe command result was not observed")
            require_equal(read_answer(workspace), {"status": "degraded", "exit_code": 3, "healthy": 2, "total": 3, "retry": False})
        elif identifier == "B6.4":
            require(command_observed(events, stderr_contains="Ran 2 tests"), "Public tests were not observed passing")
        elif identifier == "B7.4":
            require_equal(read_answer(workspace), maintenance_answer(fixture))
        elif identifier == "B8.4":
            require_equal(read_answer(workspace), stock_answer(fixture))
        elif identifier in ("B9.1", "B9.2", "B9.3"):
            # Independently annotated outputs for the explicitly closed style grammars.
            name, expected = {
                "B9.1": ("notice.txt", "Сервис: Atlas\nДата: 2026-12-02\nОкно: 09:00–09:30 UTC\n"),
                "B9.2": ("update.txt", "Atlas: работа восстановлена.\nВремя восстановления: 14:05 UTC.\n"),
                "B9.3": ("answer.txt", "status ready owner ops\n"),
            }[identifier]
            require(read_file(workspace, name).decode("utf-8") == expected, "Facts or requested style constraints differ")
        elif identifier == "C1":
            preserve(case, workspace, (case["source_file"],))
            require(command_observed(events, stderr_contains="Ran 2 tests"), "Regression tests were not observed passing")
        elif identifier == "C2":
            preserve(case, workspace)
            require_equal(read_answer(workspace), department_answer(fixture))
        elif identifier == "C3":
            preserve(case, workspace, ("main.py", "README.md"))
            expected = fixture["README.md"].replace("TODO", "python main.py 1h2m3s -> 3723").encode()
            require(read_file(workspace, "README.md") == expected, "README changes exceed the Usage update")
            duration_integration(workspace, events)
        elif identifier == "C4":
            preserve(case, workspace)
            require(read_file(workspace, "public-notice.txt").decode("utf-8") == incident_notice(fixture), "Public notice differs from current incidents or style")
        else:
            raise ValueError("Unknown additional task")
        if case.get("code_task"):
            require(code_evaluator is not None, "Task requires an isolated Python-function evaluator")
            return code_evaluator.check(case["code_task"], workspace, source_file=case["source_file"])
        return {"pass": True, "reason": "ok"}
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, RecursionError) as exc:
        return {"pass": False, "reason": str(exc)}
