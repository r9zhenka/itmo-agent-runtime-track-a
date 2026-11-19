"""Measure filesystem calls on the server's actual FUSE mount, without an LLM.

Only the temporary fixture created by scripts.measure_mount is accepted. Timers
are inside this process and therefore exclude SSH transport/process startup.
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

from runtime.mount_lease import check_lease
from runtime.remote_mount import host_settings
from scripts.measure_common import environment, summarize_records

DEFAULT_FILES = 32
DEFAULT_SMALL_BYTES = 4096
DEFAULT_LARGE_BYTES = 4 * 1024 * 1024
DEFAULT_WRITE_BYTES = 1024 * 1024
METRICS = ("stat_ms", "tree_ms", "small_read_batch_ms", "large_read_ms", "write_close_ms")


def payload(size, marker=65):
    return bytes([marker]) * size


def prepare_fixture(root, files=DEFAULT_FILES, small_bytes=DEFAULT_SMALL_BYTES,
                    large_bytes=DEFAULT_LARGE_BYTES, write_bytes=DEFAULT_WRITE_BYTES):
    root = Path(root)
    root.mkdir()
    for index in range(files):
        path = root / "small" / f"group-{index // 8}" / f"file-{index:03}.bin"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload(small_bytes))
    (root / "large.bin").write_bytes(payload(large_bytes, 66))
    (root / "write.bin").write_bytes(payload(write_bytes, 67))
    config = {"files": files, "small_bytes": small_bytes, "large_bytes": large_bytes,
              "write_bytes": write_bytes, "fixture": "project-a-fs-measurement-v1"}
    (root / "measurement.json").write_text(json.dumps(config))
    return config


def measure(root, repeats):
    root = Path(root)
    config = json.loads((root / "measurement.json").read_text())
    if config.get("fixture") != "project-a-fs-measurement-v1":
        raise ValueError("Not a filesystem measurement fixture")
    files, small_bytes = config["files"], config["small_bytes"]
    large_bytes, write_bytes = config["large_bytes"], config["write_bytes"]
    if not 1 <= files <= 256 or not all(type(n) is int and 1 <= n <= 16 * 1024 * 1024
                                      for n in (small_bytes, large_bytes, write_bytes)):
        raise ValueError("Measurement fixture exceeds supported bounds")
    names = [root / "small" / f"group-{index // 8}" / f"file-{index:03}.bin" for index in range(files)]
    expected_paths = {str(path.relative_to(root)) for path in names}
    expected_paths.update({"small", "large.bin", "write.bin", "measurement.json"})
    expected_paths.update(f"small/group-{index // 8}" for index in range(files))
    records = []

    def timed(operation):
        started = time.perf_counter_ns()
        value = operation()
        return (time.perf_counter_ns() - started) / 1_000_000, value

    for repeat in range(repeats):
        row = {"repeat": repeat + 1}
        row["stat_ms"], info = timed(names[0].stat)
        if info.st_size != small_bytes:
            raise AssertionError("stat returned the wrong size")
        row["tree_ms"], entries = timed(lambda: [str(path.relative_to(root)) for path in root.rglob("*")])
        if set(entries) != expected_paths or len(entries) != len(expected_paths):
            raise AssertionError("Tree traversal missed or duplicated fixture entries")
        row["small_read_batch_ms"], contents = timed(lambda: [path.read_bytes() for path in names])
        if any(content != payload(small_bytes) for content in contents):
            raise AssertionError("Small-file read returned incorrect bytes")
        row["large_read_ms"], content = timed(lambda: (root / "large.bin").read_bytes())
        if content != payload(large_bytes, 66):
            raise AssertionError("Large-file read returned incorrect bytes")
        content = payload(write_bytes, 68 + repeat % 20)
        # close() is inside Path.write_bytes; on uncached rclone it acknowledges PUT.
        row["write_close_ms"], count = timed(lambda: (root / "write.bin").write_bytes(content))
        if count != write_bytes or (root / "write.bin").read_bytes() != content:
            raise AssertionError("Write/close did not publish the expected bytes")
        records.append(row)
    return {"environment": environment(), "fixture": config, "raw": records,
            "summary": summarize_records(records, METRICS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--repeats", type=int, default=10)
    args = parser.parse_args()
    if not re.fullmatch(r"remote-[0-9a-f]{32}", args.workspace) or not 10 <= args.repeats <= 100:
        parser.error("Use a remote workspace ID and 10..100 repeats")
    config = host_settings()
    root = Path(config["WORKSPACE_ROOT"])
    check_lease(root, args.workspace, "rw")
    path = root / args.workspace
    if not os.path.ismount(path):
        raise RuntimeError("The target is not a mounted filesystem")
    result = measure(path, args.repeats)
    check_lease(root, args.workspace, "rw")
    result["backend"] = "server host filesystem calls through real rclone FUSE + SSH + client WebDAV"
    result["is_mount"] = True
    print(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
