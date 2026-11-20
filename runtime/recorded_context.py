"""Versioned portability for the initial long-ls block of recorded smoke commands.

Only an actual leading `ls -la /work[/path]` or `ls -al /work[/path]` command is
eligible. FUSE vs bind metadata is ignored: blocks, modes, uid/gid, link counts,
timestamps and directory sizes. Names, entry types, regular-file sizes, order,
following output and all operation status fields remain significant.
"""
import copy
import json
import re

NORMALIZER = "project-a-observation-v2"
SEARCH_COMMAND = "cd /work && find . -type f | sort && echo '---' && grep -rn \"parse_date\" . && echo '---' && cat README.md"
FIND_COMMAND = "ls -la /work && find /work -maxdepth 2 -type f | head -50"
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


def normalize_fixture_enumeration(stdout, command, task):
    """Normalize two proven filesystem-enumeration differences in fixed fixtures.

    No arbitrary grep/find output is treated as unordered. Exact command/task,
    record grammar, section boundaries and fixture cardinality are required.
    Sorting retains duplicate records; changed membership/content still differs.
    """
    lines = stdout.splitlines(keepends=True)
    if task == "B2.1" and command == SEARCH_COMMAND:
        separators = [index for index, line in enumerate(lines) if line == "---\n"]
        if len(separators) != 2:
            return stdout
        first, second = separators
        records = lines[first + 1:second]
        if len(records) != 3 or not all(re.fullmatch(
                r"\./(?:README\.md|src/(?:dates|main)\.py):[1-9][0-9]*:[^\r\n]+\n", line) for line in records):
            return stdout
        return "".join(lines[:first + 1] + sorted(records) + lines[second:])
    if task == "B9.1" and command == FIND_COMMAND:
        # The original fixture has exactly two files, below head's 50-row cap.
        # ls stays ordered; only the subsequent complete two-path find block sorts.
        if (len(lines) == 7 and lines[0] == "<ls-total>\n"
                and all(re.fullmatch(r"/work/(?:facts\.json|style\.md)\n", line) for line in lines[-2:])):
            return "".join(lines[:-2] + sorted(lines[-2:]))
    return stdout


def portable_context_digest(messages, tools):
    from baf.cases import cases, prompt
    from .model_recording import context_digest
    normalized = copy.deepcopy(messages)
    eligible = set()
    commands = {}
    task = next((case["id"] for case in cases() if case["id"] in ("B2.1", "B9.1")
                 and len(messages) > 1 and messages[1].get("role") == "user"
                 and messages[1].get("content") == prompt(case)), None)
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
                commands[call.get("id")] = command
        if message.get("role") == "tool" and message.get("tool_call_id") in commands:
            result = json.loads(message["content"])
            if isinstance(result.get("stdout"), str):
                if message.get("tool_call_id") in eligible:
                    result["stdout"] = normalize_ls(result["stdout"])
                result["stdout"] = normalize_fixture_enumeration(
                    result["stdout"], commands[message["tool_call_id"]], task)
            message["content"] = json.dumps(result)
    return context_digest(normalized, tools)
