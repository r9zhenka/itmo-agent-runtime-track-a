"""Container-only function adapter. No test oracles and no host-side imports."""
import importlib.util
import json
import sys
from pathlib import Path


def require_json_value(value):
    """Do not silently coerce tuples, custom objects or non-string mapping keys."""
    if type(value) in (str, int, float, bool, type(None)):
        return
    if type(value) is list:
        for item in value:
            require_json_value(item)
        return
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            require_json_value(item)
        return
    raise TypeError("Return value must contain only JSON-compatible built-in types")


def main():
    stage = "load"
    try:
        function, value = sys.argv[1], json.loads(sys.argv[2])
        spec = importlib.util.spec_from_file_location("candidate", Path.cwd() / "solution.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        stage = "call"
        answer = getattr(module, function)(value)
        require_json_value(answer)
        print(json.dumps({"value": answer}, ensure_ascii=True, allow_nan=False))
        return 0
    except BaseException as exc:
        # No traceback, source contents or unrestricted exception messages.
        print(json.dumps({"error": type(exc).__name__, "stage": stage}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
