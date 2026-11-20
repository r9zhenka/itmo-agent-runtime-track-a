# 0006 — Single-user sessions and exclusive workspaces

Status: accepted; extended for Checkpoint 2.

## Decision

One installation serves one trusted user with a client bearer token. Each session
owns one workspace and mode, its conversation, event log and operation results.
Only one run per session may execute. Distinct, non-overlapping workspaces can run
in parallel. Overlapping workspace reservations are rejected, including parent/child
directories. A local human can still edit files concurrently; there is no
distributed edit lock. WriteFile replaces its target atomically. Remote shell I/O
is limited to the filesystem subset documented in [ADR 0005](0005-mounting.md),
including whole-file writes rather than append or random writes.

The primary remote workspace is protected by an expiring mount lease and the
client exporter's 256 MiB / 4096-entry allocation bounds. Local read-write binds
require `ALLOW_LOCAL_RW=1` for trusted development (runtime/Compose default `0`,
development `.env.example` value `1`); they do not provide an aggregate quota.
See [ADR 0002](0002-sandbox.md) for the isolation and quota boundary.

Cancellation is terminal for the session. Release cancels, waits for command cleanup
and frees the workspace reservation. Existing result/event records remain available
for reconnection until the server process exits. Explicit capacity limits bound
the number of sessions, runs and operations.

Losing the remote mount lease stops affected commands with a transport error.
Transport failure can leave an operation's effects ambiguous: a write may have
completed before its response was lost. Reconnection therefore does not
automatically reexecute commands or replay failed writes. The user must inspect
the workspace before explicitly starting another run.

Command deadlines are also recorded in Docker labels. The manager enforces them
while alive; an independent watchdog enforces them after manager loss. Harness
loss does not remove the deadline. Both services share the privileged Docker
control plane, so this protects against individual process failure, not loss of
Docker or both control-plane services. Cleanup does not recover the session.

## Alternatives

- Multiple concurrent agents on one folder: useful collaboration, but requires
  explicit conflict/locking semantics. Deferred.
- Database-backed sessions and event logs: necessary for durable recovery, but
  adds migrations and transactional coordination to this checkpoint.

## Consequences

The model is simple enough to explain and test. Server process restart invalidates
the in-memory state owned by that process, including session IDs or replay cursors;
there is no durable session recovery. There is no automatic idle expiry yet.
Multi-user ownership, distributed concurrent-edit conflict detection and durable
recovery remain outside this checkpoint.
