# 0006 — Token-owned sessions and exclusive workspaces

Status: accepted; extended for Checkpoint 2.

## Decision

The initial CP1 installation used one shared client bearer token. The CP2 audit
extends this to named API principals: `CLIENT_TOKEN` supplies `default`, and
`CLIENT_IDENTITIES_JSON` supplies optional additional distinct tokens. Gateway
checks the session owner on every RPC and SSE read; create-request IDs are scoped
to principal. The SSH/host administration boundary remains trusted: this is not
OS-account isolation or a per-principal workspace entitlement system. Each session
owns one workspace and mode, its conversation, event log and operation results.
Only one run per session may execute. Distinct, non-overlapping workspaces can run
in parallel. Overlapping workspace reservations are rejected, including parent/child
directories. A local human can still edit files concurrently; there is no
distributed edit lock. Local WriteFile uses atomic replacement; the remote exporter
adds optimistic version/ETag checks before PUT/MOVE/DELETE. A final race against a
local editor remains between checking and mutation. Remote shell I/O
is limited to the filesystem subset documented in [ADR 0005](0005-mounting.md),
including whole-file writes rather than append or random writes.

The primary remote workspace is protected by an expiring mount lease and the
client exporter's 256 MiB / 4096-entry allocation bounds. Local read-write binds
require `ALLOW_LOCAL_RW=1` for trusted development (runtime/Compose default `0`,
development `.env.example` value `1`); they do not provide an aggregate quota.
See [ADR 0002](0002-sandbox.md) for the isolation and quota boundary.

Cancellation is terminal for the session. Release cancels, waits for command cleanup
and frees the workspace reservation. Once cancellation begins, only the cancel
path publishes its terminal result after cleanup confirmation; cleanup failure
is an error. The run worker cannot race it to a premature clean cancellation.
Result/event records remain reconnectable only while retained in memory.

The harness allows 128 active sessions, separately from a 128-closed-session
retention target. The manager allows 512 active sessions with the same closed
retention target. Pruning occurs on new create/provision, so closed history can
temporarily exceed the target until that trigger. Eviction removes the old
idempotency/event history. There are also 16 runs per harness session and 256
operations per sandbox session. Sequential released sessions no longer consume
the active-session limit permanently.

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
API session ownership is implemented; isolated OS tenants, distributed editor
locking and durable recovery remain outside this checkpoint. Parent/child client
exports are rejected with per-user kernel locks, which are released on exporter
process death. See the [detailed component lifecycle](../cp2-architecture.md).
