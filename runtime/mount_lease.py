"""Host-written leases, visible through the manager's read-only workspace bind.

No credentials or user files are stored here. A dead helper cannot renew a lease.
"""
import json
import math
import os
import re
import time
from pathlib import Path

from .common import Fault

PREFIX = "remote-"
CONTROL = ".remote-control"
TTL = 10


def lease_name(workspace):
    parts = Path(workspace).parts
    if parts and parts[0] == CONTROL:
        raise Fault("validation", "Mount control directory is not a workspace")
    if parts and parts[0].startswith(PREFIX):
        if len(parts) != 1 or not re.fullmatch(r"remote-[0-9a-f]{32}", workspace):
            raise Fault("validation", "Use the exact remote workspace returned by the mount helper")
        return workspace
    return None


def check_lease(root, workspace, mode):
    name = lease_name(workspace)
    if name is None:
        return
    try:
        value = json.loads((Path(root) / CONTROL / (name + ".json")).read_text())
        expires = value["expires"]
        if (not isinstance(expires, (int, float)) or not math.isfinite(expires)
                or expires <= time.time() or value["mode"] != mode):
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
        raise Fault("transport", "Client folder disconnected or mount lease expired; reconnect the folder", 503) from None


def write_lease(root, workspace, mode, expires):
    if lease_name(workspace) is None:
        raise ValueError("Not a remote workspace")
    directory = Path(root) / CONTROL
    directory.mkdir(mode=0o755, exist_ok=True)
    if directory.is_symlink():
        raise ValueError("Mount control directory cannot be a symlink")
    directory.chmod(0o755)
    target = directory / (workspace + ".json")
    temp = target.with_suffix(".tmp")
    with temp.open("w") as file:
        json.dump({"mode": mode, "expires": expires}, file)
    # The manager runs as root with all capabilities dropped; metadata is public,
    # so it must be readable without CAP_DAC_OVERRIDE. No tokens live here.
    os.chmod(temp, 0o644)
    os.replace(temp, target)
