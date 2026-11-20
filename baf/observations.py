"""Observed unittest summaries; independent task/file/code oracles still apply."""
import re


def observed_passing_unittest(events, expected_tests):
    """Accept a complete successful summary on either stream, never just a count.

    This is observed tool-output evidence, not proof against a deliberately forged
    log. Final project files are checked independently by the task's byte oracle.
    """
    summary = re.compile(
        rf"^Ran {expected_tests} tests? in [0-9]+(?:\.[0-9]+)?s\r?\n"
        r"(?:[ \t]*\r?\n)*OK[ \t]*\r?$", re.MULTILINE)
    failure = re.compile(r"^(?:FAILED\b|FAIL:|ERROR:)", re.MULTILINE)
    for event in events:
        if event.get("type") != "tool_result" or event.get("tool") != "RunCommand":
            continue
        result = event.get("result")
        if not isinstance(result, dict):
            continue
        if (type(result.get("exit_code")) is not int or result["exit_code"] != 0
                or result.get("error", "missing") is not None
                or result.get("truncated") is not False):
            continue
        streams = (result.get("stdout"), result.get("stderr"))
        if not all(isinstance(stream, str) for stream in streams):
            continue
        if any(failure.search(stream) for stream in streams):
            continue
        if any(summary.search(stream) for stream in streams):
            return True
    return False


def observed_stdout_line(events, expected):
    """Recognize one whole program-output line within a successful shell result."""
    for event in events:
        if event.get("type") != "tool_result" or event.get("tool") != "RunCommand":
            continue
        result = event.get("result")
        if not isinstance(result, dict):
            continue
        if (type(result.get("exit_code")) is not int or result["exit_code"] != 0
                or result.get("error", "missing") is not None
                or result.get("truncated") is not False):
            continue
        stdout = result.get("stdout")
        if isinstance(stdout, str) and expected in stdout.splitlines():
            return True
    return False
