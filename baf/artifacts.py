"""Bounded artifact reads pinned to directory descriptors, including parent paths."""
import os
import stat
from pathlib import Path


def read_file(workspace, relative, limit=65536):
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(part in (".", "..") for part in parts):
        raise ValueError("Invalid artifact path")
    parent = os.open(workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ValueError("Artifact must be a single-link regular file")
            with os.fdopen(fd, "rb", closefd=False) as file:
                data = file.read(limit + 1)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    if len(data) > limit:
        raise ValueError("Artifact exceeds size limit")
    return data
