# 0003 — HTTP JSON and SSE for the client

Status: accepted; SSH encapsulation added for remote folders.

## Decision

Use authenticated JSON RPC for session/message/cancel/release requests. Return
ordered events as finite SSE batches. Reconnect with the last event sequence ID.
The desktop UI and CLI share `client/api.py`; neither contains a separate protocol.

## Alternatives

- WebSocket: convenient full-duplex transport, but requires more connection-state
  and client-library code than this checkpoint needs.
- Periodic JSON polling: easy to implement, but loses compatibility with standard
  event-stream viewers and is less explicit about progress semantics.

## Consequences

The protocol works with standard HTTP tooling. A lost event connection never
resubmits a message. Batches create repeated connections but bound memory and idle
connections. Commands currently report stdout/stderr on completion, not per chunk.
Loopback HTTP is the default. Remote-folder clients reach the gateway through an
authenticated OpenSSH local forward with strict host-key checking; HTTP and bearer
tokens do not travel in plaintext across the remote network. Direct public HTTP
exposure remains unsupported. See [mounting](0005-mounting.md).
