"""Bounded data-only JSON output reading shared by benchmark checkers."""
import json
import os
import stat
from pathlib import Path


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError("Non-JSON constant: " + value)


def read_answer(workspace):
    fd = os.open(Path(workspace) / "answer.json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    # Own the descriptor before validating its type, including directory/FIFO cases.
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("answer.json must be a single-link regular file")
        with os.fdopen(fd, "rb", closefd=False) as file:
            raw = file.read(65537)
    finally:
        os.close(fd)
    if not raw or len(raw) > 65536:
        raise ValueError("answer.json must contain 1..65536 bytes")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant)


def require_equal(actual, expected):
    # JSON types matter: Python equality alone accepts False == 0 and 1 == 1.0.
    options = {"sort_keys": True, "separators": (",", ":"), "allow_nan": False}
    if json.dumps(actual, **options) != json.dumps(expected, **options):
        raise ValueError("answer.json does not match the required result, evidence or schema")
