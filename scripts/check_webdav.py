"""Exercise our exporter using real pinned rclone, without needing FUSE or Docker."""
import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from client.workspace_server import WorkspaceServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rclone", default="rclone")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root / "client"
        folder.mkdir()
        (folder / "from-client.txt").write_text("client original")
        export = WorkspaceServer(folder)
        env = {k: v for k, v in os.environ.items() if not k.startswith("RCLONE_")}
        env.update(RCLONE_WEBDAV_URL=f"http://127.0.0.1:{export.port}/",
                   RCLONE_WEBDAV_VENDOR="other", RCLONE_WEBDAV_BEARER_TOKEN=export.token)

        def call(*arguments, succeeds=True):
            result = subprocess.run([args.rclone, *arguments, "--config", "/dev/null", "--retries", "1",
                                     "--low-level-retries", "1", "--timeout", "3s"],
                                    env=env, capture_output=True, text=True, timeout=15)
            if (result.returncode == 0) != succeeds:
                raise AssertionError(result.stderr)
            return result.stdout

        try:
            listing = json.loads(call("lsjson", ":webdav:"))
            assert [entry["Name"] for entry in listing] == ["from-client.txt"]
            assert call("cat", ":webdav:from-client.txt") == "client original"
            source = root / "upload.txt"
            source.write_text("server write")
            call("copyto", str(source), ":webdav:sub/agent.txt")
            assert (folder / "sub/agent.txt").read_text() == "server write"
            call("moveto", ":webdav:sub/agent.txt", ":webdav:sub/renamed.txt")
            assert (folder / "sub/renamed.txt").read_text() == "server write"
            # rcat sends an unknown-length/chunked stream, as uncached mount uploads do.
            result = subprocess.run([args.rclone, "rcat", ":webdav:stream.txt", "--config", "/dev/null",
                                     "--streaming-upload-cutoff", "0", "--retries", "1"],
                                    input=b"streamed", env=env, capture_output=True, timeout=15)
            assert result.returncode == 0, result.stderr
            assert (folder / "stream.txt").read_bytes() == b"streamed"
            (folder / "from-client.txt").write_text("client changed")
            assert call("cat", ":webdav:from-client.txt") == "client changed"
            call("deletefile", ":webdav:sub/renamed.txt")
            assert not (folder / "sub/renamed.txt").exists()
            (folder / ".git").mkdir()
            (folder / ".git/config").write_text("private")
            call("cat", ":webdav:.git/config", succeeds=False)
            export.mode = "ro"
            call("copyto", str(source), ":webdav:forbidden.txt", succeeds=False)
            assert not (folder / "forbidden.txt").exists()
        finally:
            export.close()
    print("PASS: real rclone WebDAV listing, reads, writes, streaming PUT, rename, delete, local edits, protected paths and read-only")


if __name__ == "__main__":
    main()
