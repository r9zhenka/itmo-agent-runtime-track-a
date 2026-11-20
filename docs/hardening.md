# Sandbox hardening and failure boundary

The production workdir is the client's quota-controlled WebDAV export mounted by
rclone/FUSE. An execution container has no network interfaces except loopback,
no Docker socket, no provider credentials, a non-root UID, dropped capabilities,
`no-new-privileges`, a read-only image, a 64 MiB `/tmp`, 256 MiB RAM without swap,
64 PIDs, and one CPU of bandwidth. Open descriptors are limited to 256 and the
hard per-file size limit is 128 MiB. File tools additionally reject path escape,
protected `.git` paths and symlinks. These are defense layers, not a claim that a
container is a separate kernel or safe against kernel vulnerabilities.

## Remote workdir allocation bounds

`client/workspace_server.py` enforces a default aggregate limit of **256 MiB of
exported regular-file content** and **4096 exported entries**. Both directory and
file entries count. Individual uploads remain limited to 64 MiB, and path depth
is limited to 64 components. These are logical content/entry bounds, not byte-exact
filesystem block accounting; directory/inode overhead is bounded through the entry
limit, while the client filesystem may use additional metadata/journal space.

All remote mutations are serialized under one exporter lock. Before an upload,
the exporter counts the existing tree using descriptor-relative traversal without
following symlinks. Each incoming chunk reserves capacity **before** writing it.
The old target file remains allocated while its replacement is staged, so peak
old-plus-new data and one temporary entry count toward the bounds. At full quota,
even an equal-size replacement may require first deleting some other data. After
upload, usage is rechecked before atomic replacement. An over-budget request gets
HTTP 507 and its staging file is removed; the previous target remains untouched.
Empty files and new directories consume entries, preventing a small-file/inode
storm from bypassing the byte bound. DELETE can free capacity; file MOVE cannot
increase the allocated content/entry count.

Protected `.git` directories and reserved staging names are excluded from the
exported tree. The agent cannot create or mutate them through the exporter. The
current staging reservation is accounted explicitly. Host-user edits are trusted:
the export does not impose an OS quota on the user, and a simultaneous local edit
can grow the directory independently of the agent. The exporter notices such
growth before subsequent writes and before committing an upload. Never describe
this as protection against a malicious local administrator.

The default constants are in `client/workspace_server.py`. Programmatic tests can
construct `WorkspaceServer(..., max_bytes=..., max_entries=...)` with smaller limits.
An existing over-budget folder remains readable; writes requiring reservations
fail until usage is reduced. No initial copy or synchronization is made.

## Local direct-bind development mode

A plain Docker bind mount cannot portably impose an aggregate filesystem quota.
Consequently runtime `SandboxManager` refuses local read-write workspaces unless
`ALLOW_LOCAL_RW=1` explicitly enables trusted development. Read-only local snapshots
(including isolated B6 grading) do not require this option. Trusted offline replay,
Docker acceptance fixtures and local performance fixtures opt in explicitly.

The per-file hard limit still applies in this mode, but many separate files could
fill the backing disk. It is **not** an aggregate quota. Use the primary remote
export path for untrusted model tasks, or provision and independently verify an
external filesystem quota for local workspaces. Do not run arbitrary model-generated
commands on a local read-write bind just because `ALLOW_LOCAL_RW` is available.

## Independent command deadlines

Every execution container receives immutable control-plane labels identifying its
instance, session, operation, workspace, mode and absolute deadline. The manager
continues to enforce its monotonic timeout and synchronous cancellation. In addition,
`runtime/sandbox_watchdog.py` runs as a **separate Compose service** and scans Docker
every 250 ms for the instance's containers carrying `project-a.guard=v1`.

The watchdog force-removes a container when its labelled deadline expires, its
deadline metadata is invalid, or its remote mount lease is lost. Labels are set
when the container is created, before command execution; the sandbox has no Docker
API access and cannot extend them. Force removal kills detached descendants too.
The watchdog has no mutation HTTP API and checks ownership labels again before
removing anything. It never acts on unlabelled services or another instance.

The manager and watchdog are both in the privileged Docker control-plane boundary
and therefore both need the Docker socket. The watchdog gets only public lease
metadata from the workspace-root bind, not model credentials. This deliberately
extends the original manager-only socket policy to remove the manager process as
a single point of deadline failure. The execution sandbox never gets the socket.

If the harness crashes, the manager still times out the command. If the manager
crashes or is killed, the separate watchdog applies the recorded deadline. Manager
restart also cleans instance-labelled leftovers. Docker API latency can delay
cleanup beyond the 250 ms poll interval. If Docker itself or both control-plane
services are unavailable, timely removal is not guaranteed until they recover;
kernel resource limits and remote-export quotas remain applicable. Deadline labels
use the Docker host's wall clock, so the host clock is trusted. Session/event
state is still in memory and is not recovered as an ongoing conversation.

## Reproduction and evidence

```bash
# Offline regressions (loopback HTTP sockets, no Docker or LLM):
python3 -m unittest tests.test_hardening tests.test_runtime tests.test_remote_mount -v

# Actual resource exhaustion and crash recovery, after building the sandbox image:
python3 -m scripts.hardening_check
```

The real check uses disposable directories and only its own labelled containers.
It runs CPU load, RAM exhaustion, a bounded process-spawn storm, a per-file write
limit probe, external-symlink/canary and network/secret checks, aggregate HTTP export
quota checks, and kills isolated test manager/harness processes while commands run.
It never kills the user's Compose services. CPU is tightened to 0.25 CPU for the
probe so throttling is observable on a one-vCPU machine; the file-size probe is
tightened to 1 MiB to avoid unnecessary host allocation. The normal production
profile is asserted separately by the Docker configuration tests. RAM/PID probes
use the production limits. The independent watchdog is invoked by the surviving
test process during the crash checks, using the same implementation as the service.

Raw verdicts go to `results/hardening.json`. A successful unit test is not evidence
that the Docker kernel limits or independent crash cleanup actually ran; only the
real acceptance command provides that evidence. No model-quality claim follows
from these infrastructure probes.
