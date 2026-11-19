import argparse
import json
import os
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from collections import deque
from pathlib import Path

from baf.cases import cases, check, prepare, prompt
from baf.code_evaluator import FunctionEvaluator
from client.api import Client, settings
from client.remote import RemoteClient


def run_case(client, case, root, repeat=1, code_evaluator=None):
    name = "baf-" + case["id"].replace(".", "-") + "-" + uuid.uuid4().hex[:10]
    workspace = Path(root) / name
    prepare(case, workspace)
    sid, events = None, []
    started = time.monotonic()
    try:
        sid = client.create(str(workspace.resolve()) if isinstance(client, RemoteClient) else name)
        run = client.send(sid, prompt(case))
        events = list(client.watch(sid, run))
        final = next(e for e in reversed(events) if e["type"] == "result" and e["run_id"] == run)
        generation_ms = round((time.monotonic() - started) * 1000, 3)
        if case.get("check") == "python_function" or case.get("code_task"):
            # Stop all agent processes before taking a stable data-only snapshot.
            # Hidden inputs/results never enter the agent's conversation.
            client.release(sid)
            sid = None
            code_evaluator = code_evaluator or FunctionEvaluator()
        verdict = check(case, workspace, events, code_evaluator)
        verdict["pass"] &= final["outcome"] == "success"
        if final["outcome"] != "success":
            verdict["reason"] = json.dumps(final.get("error", final["outcome"]))
        models = [{"provider": e["provider"], "model": e["model"]} for e in events if e["type"] == "model"]
        return {"task": case["id"], "repeat": repeat, **verdict,
                "error_kind": (final.get("error") or {}).get("kind"),
                "duration_ms": round((time.monotonic() - started) * 1000, 3), "generation_ms": generation_ms,
                "tokens": final["tokens"], "model": models[0] if models else None,
                "session_id": final["session_id"], "trace_id": run, "workspace": str(workspace)}
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
    parser.add_argument("--ssh-host", help="Run against an SSH server, exporting each fresh local fixture")
    parser.add_argument("--server-repo")
    parser.add_argument("--ssh-config")
    parser.add_argument("--ssh-port", type=int, default=22)
    parser.add_argument("--gateway-port", type=int, default=18080)
    parser.add_argument("--token-budget", type=int, default=100000000,
                        help="Stop campaign before another run when reported usage reaches this budget")
    parser.add_argument("--parallel", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--run-token-reserve", type=int, default=4000000,
                        help="Reserve conservative headroom per in-flight run before scheduling")
    args = parser.parse_args()
    selected = [c for c in cases() if (not args.smoke or c["id"].endswith(".1")) and (not args.task or c["id"] == args.task)]
    if not selected or args.repeats < 1 or args.token_budget < args.run_token_reserve or args.run_token_reserve < 1:
        parser.error("Select an existing task and a positive repeat count")
    if args.ssh_host and not args.server_repo:
        parser.error("--ssh-host requires --server-repo")
    def execute(case, repeat):
        client = (RemoteClient(args.token, args.ssh_host, args.server_repo, args.ssh_port,
                               args.gateway_port, args.ssh_config) if args.ssh_host else Client(args.server, args.token))
        try:
            result = run_case(client, case, args.root, repeat)
        except Exception as exc:
            result = {"task": case["id"], "repeat": repeat, "pass": False, "reason": str(exc),
                      "error_kind": getattr(exc, "kind", "unknown")}
        finally:
            if isinstance(client, RemoteClient):
                try:
                    client.close()
                except Exception as exc:
                    result.update({"pass": False, "reason": "Remote cleanup failed",
                                   "error_kind": "transport"})
        return result
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    passed, total, tokens, charged = 0, 0, 0, 0
    jobs = deque((case, repeat) for case in selected for repeat in range(1, args.repeats + 1))
    with output.open("a", encoding="utf-8") as file, ThreadPoolExecutor(max_workers=args.parallel) as pool:
        pending = set()
        while pending or jobs:
            while jobs and len(pending) < args.parallel:
                if charged + (len(pending) + 1) * args.run_token_reserve > args.token_budget:
                    break
                job = jobs.popleft()
                pending.add(pool.submit(execute, *job))
            if not pending:
                if jobs:
                    print("Campaign budget headroom exhausted; remaining runs were not started.")
                    return 2
                break
            completed, pending = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                result = future.result()
                result["pair_label"] = args.pair
                result["timestamp"] = time.time()
                tokens += result.get("tokens", 0)
                # Failed requests can consume provider tokens without reporting usage.
                uncertain = not result.get("model") or result.get("error_kind") in ("model", "timeout", "transport", "unknown")
                charged += max(result.get("tokens", 0), args.run_token_reserve if uncertain else 0)
                result["campaign_tokens"] = tokens
                result["campaign_budget_charged"] = charged
                result["quality_evaluation"] = result.get("model", {}).get("provider") == "live" if result.get("model") else False
                file.write(json.dumps(result) + "\n")
                file.flush()
                passed += result["pass"]
                total += 1
                print(f"{result['task']} #{result['repeat']}: {'PASS' if result['pass'] else 'FAIL'} — {result['reason']}", flush=True)
    print(f"{passed}/{total} passed. Raw results: {output}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
