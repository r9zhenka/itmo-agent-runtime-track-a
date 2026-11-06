import os

from .common import Remote, serve
from .contracts import CLIENT, validate_request


class Gateway:
    def __init__(self, harness):
        self.harness = harness

    def health(self):
        return {"status": "ok", "service": "gateway", "v": 0}

    def dispatch(self, body):
        op = validate_request(body, CLIENT)
        return self.harness(op, **{k: v for k, v in body.items() if k not in ("v", "op")})

    def events(self, session_id, after):
        return self.harness("events", session_id=session_id, after=after)["events"]


if __name__ == "__main__":
    serve(Gateway(Remote(os.getenv("HARNESS_URL", "http://harness:8000"),
                         os.environ["INTERNAL_TOKEN"])), os.environ["CLIENT_TOKEN"])
