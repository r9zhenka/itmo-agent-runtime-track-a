"""Independent sandbox control-plane reaper, outside manager/harness processes.

Only immutable Docker labels and public mount leases are trusted. No execution
container has the Docker socket or can extend its deadline. Like the manager,
this service is part of the privileged Docker control plane, not the sandbox.
"""
import json
import math
import os
import threading
import time
from urllib.parse import quote

from .common import Fault, serve
from .docker_engine import Docker
from .mount_lease import check_lease


def reap_once(engine, instance, root, now=None):
    now = time.time() if now is None else now
    filters = quote(json.dumps({"label": [f"project-a.instance={instance}", "project-a.guard=v1"]}))
    removed = []
    for item in engine.request("GET", "/containers/json?all=true&filters=" + filters):
        labels = item.get("Labels", {})
        # Defense in depth: never touch unrelated containers even with a faulty adapter.
        if labels.get("project-a.instance") != instance or labels.get("project-a.guard") != "v1":
            continue
        reason = None
        try:
            deadline = float(labels["project-a.deadline"])
            if not math.isfinite(deadline) or now >= deadline:
                reason = "deadline"
        except (KeyError, TypeError, ValueError):
            reason = "invalid_deadline"
        workspace = labels.get("project-a.workspace", "local")
        if reason is None and workspace != "local":
            try:
                check_lease(root, workspace, labels.get("project-a.mode"))
            except Fault:
                reason = "mount_lease"
        if reason:
            engine.remove(item["Id"])
            removed.append({"container": item["Id"], "reason": reason})
    return removed


class Watchdog:
    def __init__(self, engine, instance, root, interval=0.25):
        self.engine, self.instance, self.root, self.interval = engine, instance, root, interval
        self.last_success = 0
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                removed = reap_once(self.engine, self.instance, self.root)
                self.last_success = time.monotonic()
                for item in removed:
                    print(json.dumps({"type": "sandbox_reaped", **item}), flush=True)
            except (Fault, OSError, ValueError):
                # Health becomes unhealthy. Retry rather than forgetting deadlines.
                pass
            self.stop.wait(self.interval)

    def health(self):
        if time.monotonic() - self.last_success > 15:
            raise Fault("sandbox", "Sandbox watchdog cannot inspect Docker", 503)
        return {"status": "ok", "service": "sandbox-watchdog", "v": 0}

    def dispatch(self, body):
        raise Fault("validation", "Watchdog has no mutation API", 404)


def main():
    watcher = Watchdog(Docker(os.getenv("DOCKER_SOCKET", "/var/run/docker.sock")),
                       os.getenv("INSTANCE_ID", "checkpoint1"), "/workspaces")
    thread = threading.Thread(target=watcher.run, daemon=True)
    thread.start()
    try:
        serve(watcher, os.environ["INTERNAL_TOKEN"])
    finally:
        watcher.stop.set()
        thread.join(timeout=12)


if __name__ == "__main__":
    main()
