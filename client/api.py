import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from runtime.common import Fault, Remote, request_json


def settings(path=".env"):
    allowed = {"CLIENT_TOKEN", "GATEWAY_PORT", "WORKSPACE_ROOT"}
    values = {}
    if Path(path).is_file():
        for line in Path(path).read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key in allowed:
                values[key] = value.strip().strip("'\"")
    return values


def validate_workspace(workspace):
    if not isinstance(workspace, str) or not workspace.strip():
        raise Fault("validation", "Choose a folder before connecting, or enter demo in the Folder field.")
    if len(workspace) > 4096:
        raise Fault("validation", "The folder path is too long (maximum 4096 characters).")
    path = Path(workspace)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise Fault("validation", "Choose a subfolder of the configured workspace, or enter its relative name, such as demo.")
    return workspace


class Client:
    def __init__(self, server, token):
        self.server, self.token = server.rstrip("/"), token
        self.rpc = Remote(server, token)

    def create(self, workspace, mode="rw", request_id=None):
        validate_workspace(workspace)
        self.check_server()
        return self.rpc("create", workspace=workspace, mode=mode,
                        request_id=request_id or uuid.uuid4().hex)["session_id"]

    def check_server(self):
        # Check the public identity endpoint before sending the user's token.
        try:
            health = request_json(self.server + "/health", timeout=5)
        except Fault as exc:
            raise Fault("transport", "Cannot verify the Project A gateway: " + exc.message
                        + ". Use the gateway's published GATEWAY_PORT (default 18080).",
                        exc.status, exc.retryable) from None
        if not isinstance(health, dict) or health.get("service") != "gateway" or health.get("status") != "ok" or health.get("v") != 0:
            raise Fault("transport", "This address does not identify as the Project A gateway. Check the server address and GATEWAY_PORT.", 502)
        return health

    def send(self, session_id, text, request_id=None):
        return self.rpc("message", session_id=session_id, text=text,
                        request_id=request_id or uuid.uuid4().hex)["run_id"]

    def event_batch(self, session_id, after=0):
        query = urllib.parse.urlencode({"session_id": session_id, "after": after})
        req = urllib.request.Request(self.server + "/v0/events?" + query,
            headers={"Authorization": "Bearer " + self.token, "Accept": "text/event-stream"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=10) as response:
                for raw in response:
                    if raw.startswith(b"data: "):
                        event = json.loads(raw[6:])
                        if event["seq"] > after:
                            after = event["seq"]
                            yield event
        except urllib.error.HTTPError as exc:
            exc.close()
            raise Fault("transport", f"Event stream returned HTTP {exc.code}", exc.code,
                        retryable=exc.code >= 500) from None
        except (OSError, ValueError, urllib.error.URLError):
            raise Fault("transport", "Event connection interrupted", 502, True) from None

    def watch(self, session_id, run_id, after=0, timeout=210):
        deadline = time.monotonic() + timeout
        backoff = 0.1
        while time.monotonic() < deadline:
            try:
                for event in self.event_batch(session_id, after):
                    after = event["seq"]
                    yield event
                    if event["type"] == "result" and event["run_id"] == run_id:
                        return
                backoff = 0.1
            except Fault as exc:
                if not exc.retryable:
                    raise
                time.sleep(min(backoff, max(0, deadline - time.monotonic())))
                backoff = min(backoff * 2, 2)
        raise Fault("timeout", "Timed out waiting for run; reconnect using the last event ID", 408)

    def cancel(self, session_id):
        return self.rpc("cancel", session_id=session_id)

    def release(self, session_id):
        return self.rpc("release", session_id=session_id)

    def collect(self, session_id):
        return self.rpc("collect", session_id=session_id)


def edit(folder, name, append):
    root = Path(folder).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path == root or ".git" in path.relative_to(root).parts:
        raise Fault("validation", "Edit must stay inside the selected folder, outside .git")
    with path.open("a", encoding="utf-8") as file:
        file.write(append)
