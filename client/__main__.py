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
    gui = sub.add_parser("gui")
    mount = sub.add_parser("mount", help="Mount a local folder on another Linux machine over SSH; keep running")
    mount.add_argument("--folder", required=True)
    mount.add_argument("--mode", choices=["ro", "rw"], default="rw")
    mount.add_argument("--text", help="Run one message, wait for its result, then release and unmount")
    for remote_parser in (gui, mount):
        remote_parser.add_argument("--ssh-host", required=remote_parser is mount,
                                   help="SSH config alias or user@host (key authentication)")
        remote_parser.add_argument("--server-repo", required=remote_parser is mount,
                                   help="Absolute repository path on the Docker host")
        remote_parser.add_argument("--ssh-config", help="Optional OpenSSH client configuration file")
        remote_parser.add_argument("--ssh-port", type=int, default=22)
        remote_parser.add_argument("--gateway-port", type=int, default=18080)
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
            remote = None
            if args.ssh_host:
                if not args.server_repo:
                    raise ValueError("--server-repo is required with --ssh-host")
                remote = {"ssh_host": args.ssh_host, "server_repo": args.server_repo,
                          "ssh_port": args.ssh_port, "gateway_port": args.gateway_port, "ssh_config": args.ssh_config}
            launch(args.server, args.token, config.get("WORKSPACE_ROOT", ""), remote=remote)
        elif args.action == "mount":
            import time
            from .remote import RemoteClient
            client = RemoteClient(args.token, args.ssh_host, args.server_repo,
                                  args.ssh_port, args.gateway_port, args.ssh_config)
            try:
                sid = client.create(args.folder, args.mode)
                print(json.dumps({"session_id": sid, "server": client.server,
                                  "workspace": client.workspace, "mode": args.mode}), flush=True)
                if args.text:
                    run = client.send(sid, args.text)
                    for event in client.watch(sid, run):
                        print(json.dumps(event), flush=True)
                        if event["type"] == "result" and event["outcome"] != "success":
                            return 1
                else:
                    while True:
                        client.ensure_connected()
                        time.sleep(0.2)
            except KeyboardInterrupt:
                pass
            finally:
                client.close()
            if client.last_error:
                raise Fault("transport", client.last_error, 503)
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
