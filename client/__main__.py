import argparse
import json
import os
import sys

from runtime.common import Fault
from .api import Client, edit, settings


def main(argv=None):
    config = settings()
    parser = argparse.ArgumentParser(description="Project A desktop/headless client")
    parser.add_argument("--server", default=os.getenv("SERVER_URL", "http://127.0.0.1:" + config.get("GATEWAY_PORT", "18080")))
    parser.add_argument("--token", default=os.getenv("CLIENT_TOKEN", config.get("CLIENT_TOKEN", "")))
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("gui")
    connect = sub.add_parser("connect")
    connect.add_argument("--workspace", required=True, help="Folder relative to server WORKSPACE_ROOT")
    connect.add_argument("--mode", choices=["ro", "rw"], default="rw")
    connect.add_argument("--request-id")
    send = sub.add_parser("send")
    send.add_argument("--session", required=True)
    send.add_argument("--text", required=True)
    send.add_argument("--request-id")
    send.add_argument("--wait", action="store_true")
    watch = sub.add_parser("watch")
    watch.add_argument("--session", required=True)
    watch.add_argument("--run", required=True)
    watch.add_argument("--after", type=int, default=0)
    for name in ("cancel", "release", "collect"):
        action = sub.add_parser(name)
        action.add_argument("--session", required=True)
    change = sub.add_parser("edit")
    change.add_argument("--folder", required=True)
    change.add_argument("--file", required=True)
    change.add_argument("--append", required=True)
    args = parser.parse_args(argv)
    client = Client(args.server, args.token)
    try:
        if args.action == "gui":
            from .desktop import launch
            launch(args.server, args.token, config.get("WORKSPACE_ROOT", ""))
        elif args.action == "connect":
            print(json.dumps({"session_id": client.create(args.workspace, args.mode, args.request_id)}))
        elif args.action == "send":
            run = client.send(args.session, args.text, args.request_id)
            print(json.dumps({"run_id": run}), flush=True)
            if args.wait:
                for event in client.watch(args.session, run):
                    print(json.dumps(event), flush=True)
                    if event["type"] == "result" and event["run_id"] == run and event["outcome"] != "success":
                        return 1
        elif args.action == "watch":
            for event in client.watch(args.session, args.run, args.after):
                print(json.dumps(event), flush=True)
                if event["type"] == "result" and event["run_id"] == args.run and event["outcome"] != "success":
                    return 1
        elif args.action == "edit":
            edit(args.folder, args.file, args.append)
            print(json.dumps({"edited": args.file}))
        else:
            print(json.dumps(getattr(client, args.action)(args.session)))
        return 0
    except (Fault, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
