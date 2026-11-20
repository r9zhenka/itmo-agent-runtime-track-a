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

# Actual resource exhaustion and export quotas, after building the sandbox image:
python3 -m scripts.hardening_check

# Full isolated stack, including actual controller-crash and mount-crash checks:
make check-all CHECK_ARGS=--existing-sshd
```

The resource check uses disposable directories and only its own labelled containers.
It runs CPU load, RAM exhaustion, a bounded process-spawn storm, a per-file write
limit probe, external-symlink/canary and network/secret checks, and aggregate HTTP
export quota checks. CPU is tightened to 0.25 CPU for the probe so throttling is
observable on a one-vCPU machine; the file-size probe is tightened to 1 MiB to avoid
unnecessary host allocation. The production profile is asserted separately by the
Docker configuration tests. RAM/PID probes use the production limits.

`scripts.check_watchdog_crash`, invoked by `check_all`, kills the actual manager
and harness containers in the disposable acceptance stack. It verifies the
checkout marker, Compose project/working-directory labels, instance, service IDs
and replay mode before any destructive action. The manager-loss case requires the
surviving watchdog's own `sandbox_reaped` log for the exact command container and
its deadline. The test never calls `reap_once` itself. The harness-loss case accepts
cleanup by the surviving manager or watchdog and does not invent which actor won.
Only the test's verified service IDs are restarted afterwards. It refuses ordinary
user Compose projects. Raw output is `results/watchdog-crash.json`.

`scripts.check_mount_crash` separately SIGKILLs a disposable real SSH helper and
checks that its independent mount guard removes rclone, the FUSE mount and lease.
It does not kill a user's active mount. Exporter parent/child overlap locks and
ETag/version rechecks are covered in `tests.test_workspace_conflicts`. They do not
remove the final race window against an external local editor or provide full
POSIX semantics. See [mount lifecycle](mount-lifecycle.md).

Resource verdicts go to `results/hardening.json`; a unit test is not evidence that
kernel limits or deployed crash cleanup ran. The old historical ten-check report
included manual invocation of the reaper after worker crashes; it is retained as
historical evidence, not relabelled as a deployed independent-watchdog test. The
replacement resource script has eight checks, with the real crash tests separate.
Current acceptance status and artifact locations are in [the fixes report](cp2-fixes.md).
No model-quality claim follows from any infrastructure probe.
