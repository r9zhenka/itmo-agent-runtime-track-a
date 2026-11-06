"""Executed INSIDE the sandbox, never by the harness or manager host."""
import json
import os
import sys
from pathlib import Path


def execute(tool, args, root=Path("/work")):
    root = Path(root).resolve()
    path = (root / args["path"]).resolve()
    if path == root or not path.is_relative_to(root) or ".git" in path.relative_to(root).parts:
        raise ValueError("Path must stay in /work and outside .git")
    if tool == "ReadFile":
        with path.open("rb") as file:
            content = file.read(65537)
        if len(content) > 65536:
            raise ValueError("ReadFile limit is 64 KiB; use a bounded shell command")
        sys.stdout.write(content.decode("utf-8"))
    elif tool == "WriteFile":
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic replacement avoids partially written text from this tool.
        tmp = path.with_name(path.name + ".agent-" + str(os.getpid()))
        try:
            tmp.write_text(args["content"], encoding="utf-8")
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
        print("written")


if __name__ == "__main__":
    execute(sys.argv[1], json.loads(sys.argv[2]))
