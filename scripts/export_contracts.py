import json
from pathlib import Path

from runtime.contracts import CLIENT, SANDBOX, TOOLS, obj


def schemas():
    envelope = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
    result = {**envelope, "title": "Sandbox terminal operation result v0",
        "required": ["v", "type", "session_id", "operation_id", "stdout", "stderr", "exit_code", "error", "duration_ms", "truncated"],
        "properties": {"v": {"const": 0}, "type": {"const": "result"},
            "session_id": {"type": "string"}, "operation_id": {"type": "string"},
            "stdout": {"type": "string"}, "stderr": {"type": "string"},
            "exit_code": {"type": ["integer", "null"]}, "error": {"type": ["object", "null"]},
            "duration_ms": {"type": "number"}, "truncated": {"type": "boolean"}}}
    event = {**envelope, "title": "Client event v0", "required": ["v", "seq", "session_id", "trace_id", "run_id", "type"],
        "properties": {"v": {"const": 0}, "seq": {"type": "integer", "minimum": 1},
            "session_id": {"type": "string"}, "trace_id": {"type": "string"}, "run_id": {"type": "string"},
            "type": {"enum": ["started", "model", "tool_start", "tool_result", "result"]}},
        "allOf": [{"if": {"properties": {"type": {"const": "result"}}},
                   "then": {"required": ["outcome", "duration_ms", "tokens"], "properties": {
                       "outcome": {"enum": ["success", "error", "cancelled"]}}}}]}
    sandbox_requests = []
    for op, schema in SANDBOX.items():
        if op == "exec":
            for tool, arguments in TOOLS.items():
                sandbox_requests.append({**schema, "properties": {**schema["properties"],
                    "tool": {"const": tool}, "arguments": arguments}})
        else:
            sandbox_requests.append(schema)
    sid = {"type": "string"}
    base = {"v": {"const": 0}, "session_id": sid}
    replies = [obj(base), obj({**base, "run_id": sid}),
               obj({**base, "mode": {"enum": ["ro", "rw"]}}),
               obj({**base, "cancelled": {"const": True}}),
               obj({**base, "released": {"const": True}}),
               obj({**base, "results": {"type": "array", "items": {"type": "object"}}}),
               obj({"v": {"const": 0}, "error": obj({"kind": {"type": "string"},
                    "message": {"type": "string"}, "retryable": {"type": "boolean"}})})]
    return {
        "client-server.v0.schema.json": {**envelope, "title": "Client requests v0", "oneOf": list(CLIENT.values())},
        "harness-sandbox.v0.schema.json": {**envelope, "title": "Sandbox requests v0", "oneOf": sandbox_requests},
        "reply.v0.schema.json": {**envelope, "title": "RPC replies and errors v0", "oneOf": replies},
        "sandbox-result.v0.schema.json": result,
        "client-event.v0.schema.json": event,
    }


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "contracts"
    for name, schema in schemas().items():
        (target / name).write_text(json.dumps(schema, indent=2) + "\n")
