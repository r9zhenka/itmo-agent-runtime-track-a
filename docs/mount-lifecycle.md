# Mount ownership, overlapping exports and edit conflicts

The SSH helper (`runtime.remote_mount`) owns the gateway session and a private
control pipe to `runtime.mount_guard`. The guard is a separate ordinary-user
process, started in its own process session. It owns rclone/FUSE and the existing
10-second mount lease; it renews the lease roughly once per second while its
helper's control pipe is open. It receives an export credential through stdin,
but no client API token or Docker socket. Control descriptors are not inherited
by rclone.

Normal release first requests lease revocation and waits for the guard's
acknowledgement, then releases the gateway session and closes the guard pipe.
Helper SIGKILL also closes that pipe. The guard then revokes the lease, unmounts,
stops rclone, and removes only an empty mountpoint and its lease. It never
recursively deletes the client's files. Sandbox-manager/watchdog continue using
the same lease contract and stop execution after revocation/expiry.

Mount startup has a 35-second response budget. Cleanup normally waits at most
35 seconds; a further SIGTERM grace period is bounded too, and failure is
reported rather than called successful. FUSE unmount and rclone termination each
retain their bounded subprocess waits. An unresponsive kernel/FUSE operation,
SIGKILL of the guard itself, or host failure can still require manual cleanup.
This does not claim recovery from losing both resource owners simultaneously.

`python3 -m scripts.check_mount_crash` runs on the non-root configured mount host.
It creates a disposable loopback export and real FUSE mount, writes a file,
SIGKILLs only its test helper, and verifies that the mountpoint/lease disappear
while client files survive. It neither restarts Compose nor calls a model.
Results are written to `results/mount-crash.json`; offline fixture-process tests
alone do not establish real FUSE cleanup.

Each client export holds locks in a private per-UID registry at
`/tmp/project-a-workspace-locks-UID`. Registry entries use device/inode identities,
not paths or credentials. Every ancestor receives a shared lock and the selected
directory an exclusive lock. Thus siblings can coexist while identical or
parent/child exports conflict, including separate client processes. Kernel locks
release on process exit/SIGKILL; zero-byte lock files remain intentionally because
unlinking a potentially open lock file would split its coordination domain.
The registry rejects symlinks and ownership/permission mismatches. A trusted
local user can still rename/reparent directories or create bind aliases after
registration; this is not a filesystem namespace jail for the local user.

GET/HEAD and PROPFIND expose a strong version ETag derived from inode, length,
timestamps and mode. Mutations support `If-Match` and `If-None-Match`; a stale
precondition returns HTTP 412. PUT stages and quota-checks its replacement, then
rechecks the target version immediately before replacement. MOVE rechecks both
source and destination; DELETE rechecks its target. A detected concurrent change
returns HTTP 409, preserving the observed local change. Remote requests remain
serialized by the exporter lock.

These are optimistic checks, not a distributed editing lock. There remains a
small interval between the final stat and replace/unlink where a local editor
can change a file. Rclone need not send conditional headers for every operation;
the automatic version rechecks still apply. Local editors do not participate in
the HTTP precondition protocol. Whole-file writes remain the supported path;
append/random writes and directory MOVE are outside the filesystem subset.
