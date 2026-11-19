"""Read-only cleanup evidence for a single remote mount on the Docker host."""
import argparse
import json
import os
from pathlib import Path
from urllib.parse import quote

from runtime.docker_engine import Docker
from runtime.mount_lease import CONTROL, lease_name
from runtime.remote_mount import host_settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace")
    args = parser.parse_args()
    if lease_name(args.workspace) is None:
        raise SystemExit("Expected a remote workspace ID")
    root = Path(host_settings()["WORKSPACE_ROOT"])
    filters = quote(json.dumps({"label": ["project-a.workspace=" + args.workspace]}))
    containers = Docker().request("GET", "/containers/json?all=true&filters=" + filters)
    print(json.dumps({"mounted": os.path.ismount(root / args.workspace),
                      "directory_exists": (root / args.workspace).exists(),
                      "lease_exists": (root / CONTROL / (args.workspace + ".json")).exists(),
                      "containers": len(containers)}))


if __name__ == "__main__":
    main()
