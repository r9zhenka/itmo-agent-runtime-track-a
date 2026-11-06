# 0006 — Single-user sessions and exclusive workspaces

Status: accepted for Checkpoint 1.

## Decision

One installation serves one trusted user with a client bearer token. Each session
owns one workspace and mode, its conversation, event log and operation results.
Only one run per session may execute. Distinct, non-overlapping workspaces can run
in parallel. Overlapping workspace reservations are rejected, including parent/child
directories. A local human can still edit files concurrently; shell writes have
normal filesystem semantics, and WriteFile replaces its target atomically.

Cancellation is terminal for the session. Release cancels, waits for command cleanup
and frees the workspace reservation. Existing result/event records remain available
for reconnection until the server process exits. Explicit capacity limits bound
the number of sessions, runs and operations.

## Alternatives

- Multiple concurrent agents on one folder: useful collaboration, but requires
  explicit conflict/locking semantics. Deferred.
- Database-backed sessions and event logs: necessary for durable recovery, but
  adds migrations and transactional coordination to this checkpoint.

## Consequences

The model is simple enough to explain and test. Restart invalidates session IDs
and replay cursors. There is no automatic idle expiry yet. Multi-user ownership,
concurrent-edit conflict detection and durable recovery are CP2 extensions.
