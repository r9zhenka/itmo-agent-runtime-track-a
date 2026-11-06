# 0005 — Mounting strategy

Status: same-host bind accepted for CP1; remote mechanism proposed, not implemented.

## Context

The final assignment explicitly requires mounting a client's local folder on a
different server machine. Copying/synchronizing files does not meet that requirement.
Checkpoint 1 needs an executable path without pretending remote mounting is done.

## Decision

At CP1, require a folder under `WORKSPACE_ROOT` on the Docker host and bind-mount
it at `/work` in every command container. Read-only mode makes the whole mount
read-only. Read-write mode permits edits, with an additional read-only bind for
an existing top-level `.git`. Harness code, traces and server credentials live
outside the workspace.

For CP2, prototype client-served SFTP through a reverse SSH tunnel, with SSHFS on
the server. The client would establish the outbound tunnel; the manager would
mount the resulting filesystem into command containers. This proposal still needs
prototyping, pinned implementations, permission design and disconnect tests.

## Remote alternatives

| Approach | Benefit | Cost / uncertainty |
|---|---|---|
| SSHFS + reverse SSH tunnel | Familiar filesystem operations; client can initiate outbound connection | FUSE privileges, UID mapping, blocking I/O and reconnect semantics |
| WebDAV + rclone mount | HTTP-based transport, cross-platform serving | Cache consistency, rename semantics and credential lifecycle |
| NFS over WireGuard | Native shared filesystem semantics | VPN configuration, export permissions and cross-platform client complexity |

No latency or reliability advantage is claimed without measurements.

## Consequences

Current edits are visible through a real mount without copying. Docker bind mounts
refer to paths on the daemon host; selecting a folder on a remote laptop does not
work yet. No remote-disconnect guarantees are claimed. The original folder survives
session release and `compose down -v`; the runtime does not make a server-side copy.
Checkpoint 2 must explicitly specify cache behavior, data loss, EIO/timeouts and
what the user sees on tunnel/mount failure.
