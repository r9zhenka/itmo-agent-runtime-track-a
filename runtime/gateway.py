import hashlib
import json
import os
import threading

from .common import Fault, Remote, serve
from .contracts import CLIENT, validate_request


class Gateway:
    """Authenticate identities at the HTTP boundary; authorize every session operation.

    Identity tokens isolate sessions, not OS/SSH accounts. The host and workspace
    selection remain a trusted administration boundary.
    """
    def __init__(self, harness, retained_sessions=128):
        self.harness = harness
        self.owners = {}
        self.lock = threading.RLock()
        self.retained_sessions = retained_sessions

    def health(self):
        return {"status": "ok", "service": "gateway", "v": 0}

    def authorize(self, session_id, principal):
        with self.lock:
            state = self.owners.get(session_id)
            if state is None or state["owner"] != principal:
                # Do not reveal whether another identity's session exists.
                raise Fault("auth", "Session is unavailable to this identity", 403)

    def dispatch(self, body):
        return self.dispatch_authenticated(body, "default")

    def dispatch_authenticated(self, body, principal):
        op = validate_request(body, CLIENT)
        args = {k: v for k, v in body.items() if k not in ("v", "op")}
        if op == "create":
            # Request-id replay is scoped to identity, not to the shared gateway.
            args["request_id"] = hashlib.sha256(json.dumps(
                [principal, args["request_id"]], ensure_ascii=True).encode()).hexdigest()
            # The harness already deduplicates identity-scoped request IDs. A
            # slow upstream create must not lock authorization for other sessions.
            result = self.harness(op, **args)
            sid = result["session_id"]
            with self.lock:
                if sid in self.owners and self.owners[sid]["owner"] != principal:
                    raise Fault("auth", "Session owner mismatch", 403)
                self.owners.setdefault(sid, {"owner": principal, "closed": False})
                closed = [key for key, state in self.owners.items() if state["closed"]]
                for old in closed[:max(0, len(closed) - self.retained_sessions)]:
                    del self.owners[old]
                return result
        self.authorize(args["session_id"], principal)
        result = self.harness(op, **args)
        if op == "release":
            with self.lock:
                self.owners[args["session_id"]]["closed"] = True
        return result

    def events(self, session_id, after):
        return self.events_authenticated(session_id, after, "default")

    def events_authenticated(self, session_id, after, principal):
        self.authorize(session_id, principal)
        return self.harness("events", session_id=session_id, after=after)["events"]


def client_identities(default_token, extra_json=""):
    extra = json.loads(extra_json or "{}")
    if not isinstance(extra, dict) or "default" in extra:
        raise ValueError("CLIENT_IDENTITIES_JSON must map identity names to distinct tokens; default is reserved")
    return {"default": default_token, **extra}


if __name__ == "__main__":
    serve(Gateway(Remote(os.getenv("HARNESS_URL", "http://harness:8000"),
                         os.environ["INTERNAL_TOKEN"])),
          client_identities(os.environ["CLIENT_TOKEN"], os.getenv("CLIENT_IDENTITIES_JSON", "")))
