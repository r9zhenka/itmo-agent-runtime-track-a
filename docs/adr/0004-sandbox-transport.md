# 0004 — Versioned sandbox RPC and idempotency

Status: accepted for Checkpoint 1.

## Decision

Use JSON over internal HTTP, with version `v: 0`, a named operation, session ID,
and a unique exec operation ID. Validate requests before dispatch. Store exactly
one terminal result per operation while the manager process lives. Reusing an ID
with different arguments is an error; an in-flight duplicate gets `busy`.

Timeouts apply to HTTP, Docker calls, command execution and harness runs. A
transport error never triggers a new command ID automatically, because the first
request may already have changed files. Preserve nonzero exit codes separately
from timeout, sandbox failure and transport failure.

## Alternatives

- gRPC/protobuf: good generated clients and streaming, but adds dependencies and
  tooling that are unnecessary for the first checkpoint.
- A message broker: useful for durable scheduling, but adds deployment and
  delivery-semantics work before we have evidence it is needed.

## Consequences

Protocol messages are inspectable and reproducible. In-memory idempotency does
not survive service restart. Large artifacts are not sent in RPCs; workspace files
remain mounted. Chunked command streaming and durable operation journals are later
extensions. See `docs/protocols.md` and generated JSON Schemas.
