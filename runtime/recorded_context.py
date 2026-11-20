"""Versioned portability for the initial long-ls block of recorded smoke commands.

Only an actual leading `ls -la /work[/path]` or `ls -al /work[/path]` command is
eligible. FUSE vs bind metadata is ignored: blocks, modes, uid/gid, link counts,
timestamps and directory sizes. Names, entry types, regular-file sizes, order,
following output and all operation status fields remain significant.
"""
import copy
import json
import re

NORMALIZER = "project-a-ls-long-v1"
COMMAND = re.compile(r"^\s*ls\s+-(?:la|al)\s+/work(?:/[A-Za-z0-9_.-]+)*\s*(?:&&|;|$)")
ENTRY = re.compile(r"(?P<type>[-d])[rwxstST-]{9}[.+]?\s+\d+\s+\S+\s+\S+\s+"
                   r"(?P<size>\d+)\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+"
                   r"\d{1,2}\s+(?:\d{2}:\d{2}|\d{4})\s+(?P<name>[^\r\n]+)\r?\n?")


def normalize_ls(stdout):
    lines = stdout.splitlines(keepends=True)
    if not lines or re.fullmatch(r"total \d+\r?\n?", lines[0]) is None:
        return stdout
    entries = []
    for line in lines[1:]:
        match = ENTRY.fullmatch(line)
        if match is None:
            # A malformed apparent listing entry must never be partially masked.
            if re.match(r"[-dlbcps][rwxstST-]{9}", line):
                return stdout
            break
        kind, size, name = match.group("type", "size", "name")
        entries.append(json.dumps([kind, size if kind == "-" else "directory", name], ensure_ascii=False) + "\n")
    if not entries:
        return stdout
    return "<ls-total>\n" + "".join(entries) + "".join(lines[1 + len(entries):])


def portable_context_digest(messages, tools):
    from .model_recording import context_digest
    normalized = copy.deepcopy(messages)
    eligible = set()
    for message in normalized:
        if message.get("role") == "assistant":
            for call in message.get("tool_calls", []):
                function = call.get("function", {})
                if function.get("name") != "RunCommand":
                    continue
                try:
                    command = json.loads(function["arguments"])["command"]
                except (KeyError, TypeError, ValueError):
                    continue
                if isinstance(command, str) and COMMAND.match(command):
                    eligible.add(call.get("id"))
        if message.get("role") == "tool" and message.get("tool_call_id") in eligible:
            result = json.loads(message["content"])
            if isinstance(result.get("stdout"), str):
                result["stdout"] = normalize_ls(result["stdout"])
            message["content"] = json.dumps(result)
    return context_digest(normalized, tools)
