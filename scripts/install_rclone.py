"""Install the pinned rclone binary into a user-selected directory (no sudo)."""
import argparse
import hashlib
import io
import platform
import subprocess
import zipfile
from pathlib import Path

VERSION = "1.68.2"
ARCHES = {
    "x86_64": ("amd64", "0e6fa18051e67fc600d803a2dcb10ddedb092247fc6eee61be97f64ec080a13c"),
    "aarch64": ("arm64", "c6e9d4cf9c88b279f6ad80cd5675daebc068e404890fa7e191412c1bc7a4ac5f"),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=Path.home() / ".local/bin")
    args = parser.parse_args()
    if platform.system() != "Linux" or platform.machine() not in ARCHES:
        raise SystemExit("This installer supports Linux x86_64 and aarch64")
    arch, checksum = ARCHES[platform.machine()]
    stem = f"rclone-v{VERSION}-linux-{arch}"
    raw = subprocess.check_output(["curl", "--fail", "--location", "--silent", "--show-error",
                                   "--max-time", "120", f"https://downloads.rclone.org/v{VERSION}/{stem}.zip"])
    if hashlib.sha256(raw).hexdigest() != checksum:
        raise SystemExit("rclone archive SHA256 mismatch")
    args.dest.mkdir(parents=True, exist_ok=True)
    target = args.dest / "rclone"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        binary = archive.read(stem + "/rclone")
    # Replace a directory entry atomically; do not follow an existing symlink.
    import os
    import tempfile
    fd, temp = tempfile.mkstemp(prefix=".rclone-", dir=args.dest)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(binary)
            os.fchmod(file.fileno(), 0o755)
        os.replace(temp, target)
    finally:
        Path(temp).unlink(missing_ok=True)
    print(f"Installed rclone v{VERSION} at {target}; SHA256 verified")


if __name__ == "__main__":
    main()
