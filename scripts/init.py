import os
import secrets
from pathlib import Path

from baf.cases import cases, prepare


def main():
    root = Path(__file__).resolve().parents[1]
    env = root / ".env"
    if not env.exists():
        text = (root / ".env.example").read_text()
        replacements = {
            "replace-with-a-random-token": secrets.token_urlsafe(32),
            "replace-with-a-different-random-token": secrets.token_urlsafe(32),
            "/absolute/path/to/project-a/workspaces": "'" + str(root / "workspaces") + "'",
            "SANDBOX_UID=1000": f"SANDBOX_UID={os.getuid()}",
            "SANDBOX_GID=1000": f"SANDBOX_GID={os.getgid()}",
            "INSTANCE_ID=checkpoint1": "INSTANCE_ID=cp1-" + secrets.token_hex(4),
        }
        for source, value in replacements.items():
            text = text.replace(source, value)
        fd = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as file:
            file.write(text)
        print("Created .env with random tokens (mode 0600).")
    else:
        print("Kept existing .env.")
    demo = root / "workspaces" / "demo"
    if not demo.exists():
        prepare(cases()[0], demo)
    print("Demo folder: workspaces/demo")
    print("Next: docker compose up --build")


if __name__ == "__main__":
    main()
