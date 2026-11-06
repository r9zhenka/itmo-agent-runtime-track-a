import argparse
import json
import os
import time
import uuid
from pathlib import Path

from baf.cases import cases, check, prepare, prompt
from client.api import Client, settings


def run_case(client, case, root, repeat=1):
    name = "baf-" + case["id"].replace(".", "-") + "-" + uuid.uuid4().hex[:10]
    workspace = Path(root) / name
    prepare(case, workspace)
    sid, events = None, []
    started = time.monotonic()
    try:
        sid = client.create(name)
        run = client.send(sid, prompt(case))
        events = list(client.watch(sid, run))
        final = next(e for e in reversed(events) if e["type"] == "result" and e["run_id"] == run)
        verdict = check(case, workspace, events)
        verdict["pass"] &= final["outcome"] == "success"
        if final["outcome"] != "success":
            verdict["reason"] = json.dumps(final.get("error", final["outcome"]))
        models = [{"provider": e["provider"], "model": e["model"]} for e in events if e["type"] == "model"]
        return {"task": case["id"], "repeat": repeat, **verdict,
                "duration_ms": round((time.monotonic() - started) * 1000, 3),
                "tokens": final["tokens"], "model": models[0] if models else None,
                "session_id": sid, "trace_id": run, "workspace": str(workspace)}
    finally:
        if sid:
            client.release(sid)


def main():
    config = settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default=os.getenv("SERVER_URL", "http://127.0.0.1:" + config.get("GATEWAY_PORT", "18080")))
    parser.add_argument("--token", default=os.getenv("CLIENT_TOKEN", config.get("CLIENT_TOKEN", "")))
    parser.add_argument("--root", default=config.get("WORKSPACE_ROOT", "workspaces"))
    parser.add_argument("--pair", default="custom+replay")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--task")
    parser.add_argument("--output", default="results/baf.jsonl")
    args = parser.parse_args()
    selected = [c for c in cases() if (not args.smoke or c["id"].endswith(".1")) and (not args.task or c["id"] == args.task)]
    if not selected or args.repeats < 1:
        parser.error("Select an existing task and a positive repeat count")
    client = Client(args.server, args.token)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    passed, total = 0, 0
    with output.open("a", encoding="utf-8") as file:
        for case in selected:
            for repeat in range(1, args.repeats + 1):
                try:
                    result = run_case(client, case, args.root, repeat)
                except Exception as exc:
                    result = {"task": case["id"], "repeat": repeat, "pass": False, "reason": str(exc)}
                result["pair_label"] = args.pair
                result["timestamp"] = time.time()
                result["quality_evaluation"] = result.get("model", {}).get("provider") == "live" if result.get("model") else False
                file.write(json.dumps(result) + "\n")
                file.flush()
                passed += result["pass"]
                total += 1
                print(f"{case['id']}: {'PASS' if result['pass'] else 'FAIL'} — {result['reason']}", flush=True)
    print(f"{passed}/{total} passed. Raw results: {output}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
