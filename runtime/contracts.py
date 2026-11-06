"""Schemas use a deliberately small JSON Schema subset, validated below."""
from .common import Fault


def string(limit=4096):
    return {"type": "string", "minLength": 1, "maxLength": limit}


def obj(properties, required=None):
    return {"type": "object", "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False}


ID = {**string(64), "pattern": "^[a-zA-Z0-9_-]+$"}
MODE = {"type": "string", "enum": ["ro", "rw"]}
TOOLS = {
    "RunCommand": obj({"command": string(16000)}),
    "ReadFile": obj({"path": string()}),
    "WriteFile": obj({"path": string(), "content": {"type": "string", "maxLength": 65536}}),
}


def message(op, fields):
    return obj({"v": {"const": 0, "type": "integer"}, "op": {"const": op}, **fields})


SANDBOX = {
    "provision": message("provision", {"session_id": ID, "workspace": string(), "mode": MODE}),
    "exec": message("exec", {"session_id": ID, "operation_id": ID,
        "tool": {"enum": list(TOOLS)}, "arguments": {"type": "object"},
        "timeout_s": {"type": "number", "minimum": 0.1, "maximum": 120}}),
    **{op: message(op, {"session_id": ID}) for op in ("collect", "cancel", "release")},
}
CLIENT = {
    "create": message("create", {"request_id": ID, "workspace": string(), "mode": MODE}),
    "message": message("message", {"session_id": ID, "request_id": ID, "text": string(16000)}),
    **{op: message(op, {"session_id": ID}) for op in ("collect", "cancel", "release")},
}


def validate(value, schema, path="request"):
    import re
    types = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float)}
    kind = schema.get("type")
    if kind and (not isinstance(value, types[kind]) or (kind in ("integer", "number") and isinstance(value, bool))):
        raise Fault("validation", f"{path}: expected {kind}")
    if "const" in schema and value != schema["const"]:
        raise Fault("validation", f"{path}: invalid constant")
    if "enum" in schema and value not in schema["enum"]:
        raise Fault("validation", f"{path}: unsupported value")
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if not set(schema.get("required", [])).issubset(value):
            raise Fault("validation", f"{path}: missing required fields")
        if schema.get("additionalProperties") is False and set(value) - set(props):
            raise Fault("validation", f"{path}: unknown fields")
        for key in value.keys() & props.keys():
            validate(value[key], props[key], path + "." + key)
    if isinstance(value, str):
        if not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 1_000_000):
            raise Fault("validation", f"{path}: invalid length")
        if "pattern" in schema and not re.fullmatch(schema["pattern"], value):
            raise Fault("validation", f"{path}: invalid identifier")
    if kind in ("number", "integer"):
        import math
        if not math.isfinite(value) or not schema.get("minimum", -1e99) <= value <= schema.get("maximum", 1e99):
            raise Fault("validation", f"{path}: outside allowed range")


def validate_request(body, contracts):
    op = body.get("op")
    if not isinstance(op, str) or op not in contracts:
        raise Fault("validation", "Unknown operation")
    validate(body, contracts[op])
    return op


def tool_definitions():
    descriptions = {
        "RunCommand": "Run a shell command in /work. Inspect exit_code, stdout and stderr. Shell state does not persist.",
        "ReadFile": "Read a UTF-8 file relative to /work (maximum 64 KiB).",
        "WriteFile": "Write a UTF-8 file relative to /work, creating parent directories.",
    }
    return [{"type": "function", "function": {"name": name,
             "description": descriptions[name], "parameters": schema}}
            for name, schema in TOOLS.items()]
