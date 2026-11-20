# 0005 — Mounting strategy

Status: WebDAV over reverse SSH + rclone/FUSE accepted for the remote prototype;
real two-machine acceptance passed on Fedora → Ubuntu VM. Same-host bind remains supported.

## Context

A-2/A-3 require a true mount of a client's folder on a different server, with
bidirectional visibility, RO/RW modes, disconnect behavior and no persistent
server copy after release. CP1 only supplied a same-host bind mount. The earlier
SSHFS proposal in this ADR was not implemented.

## Decision

The Python client serves one folder over a restricted WebDAV subset on loopback.
OpenSSH forwards it to server loopback and forwards the gateway back to the client.
A host-side SSH helper starts an independent `runtime.mount_guard` process. The
guard runs rclone 1.68.2 with FUSE outside Compose, mounts below `WORKSPACE_ROOT`
and maintains an expiring lease; the helper owns the gateway session. Docker binds
that host mount at `/work`. The manager need not receive FUSE privileges or see
new submounts through its private metadata bind; the Docker daemon resolves the
source on its own host. Both processes run as the trusted SSH user. A private
control pipe ties the guard's lifetime to the helper: helper SIGKILL produces EOF,
which revokes the lease and initiates unmount without requiring helper cleanup code.

The rclone version and Linux archive hashes are pinned by the installer. Python
runtime/tests still use only the standard library. Exporter path handling uses
open directory descriptors and rejects symlinks, hard-linked files and `.git`.
RO is checked on the client as well as in FUSE and Docker. No disk cache is used.
A mount lease failure stops commands with a transport error. Cleanup is explicit
and a failed unmount is reported.

## Alternatives

| Approach | Benefits | Costs / reason not selected |
|---|---|---|
| SSHFS + reverse tunnel (previous proposal) | More complete POSIX/SFTP behavior | A safely confined SFTP endpoint on the client would require additional SSH/chroot setup or another server dependency; `sftp-server -d` alone does not confine paths |
| WebDAV + rclone/FUSE (selected) | Client-initiated tunnel, no client SSH daemon; exporter directly enforces folder and protected-path policy | We own a limited WebDAV server; uncached VFS lacks full POSIX write semantics; FUSE setup on server |
| NFS over WireGuard | Native shared filesystem and mature kernel client | VPN/export administration, more privileged client setup and broader operational complexity |
| Copy/sync | Easy deployment without FUSE | Does not satisfy the assignment's mount requirement |

## Consequences

Read, whole-file write, rename and listing work through a real filesystem mount;
networkless sandboxes only see filesystem operations. SSH authenticates and encrypts
both channels. The SSH user is trusted and this is not a multi-user hosting design.
Append/random writes, directory rename, Unix permission changes and Git access are
outside this prototype's supported filesystem subset. There is no automatic
resume of a lost mount and no automatic replay of failed writes. The exporter
reserves the selected folder and rejects overlapping parent/child exports using
per-user kernel locks. PUT/MOVE/DELETE recheck source/destination versions and
honour supported ETag preconditions. This is optimistic conflict detection,
not atomic exclusion of a local editor; a final check-to-mutation race remains.

Helper SIGKILL cleanup is delegated to the independent guard. SIGKILL of the guard
itself, FUSE/host failure or unsuccessful unmount can still require manual cleanup;
leases prevent reuse by the manager. The new guard-crash acceptance must be judged
by its own run evidence, not by the earlier ordinary-disconnect test.

Two-machine acceptance and ten-repeat filesystem measurements have been collected;
small-file batches expose a substantial round-trip cost. No performance advantage
or full POSIX equivalence is claimed. See [measurements](../cp2-report.md#measured-performance),
[setup and limitations](../remote-mount.md), and [lifecycle diagrams](../cp2-architecture.md).
