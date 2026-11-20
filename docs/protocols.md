# Protocol v0

All RPC calls are `POST /v0`, `Content-Type: application/json`, with
`Authorization: Bearer TOKEN`. Every body includes integer `v: 0` and `op`.
`GET /health` is unauthenticated and contains no sensitive configuration.

The gateway accepts `CLIENT_TOKEN`. Internal services accept a distinct
`INTERNAL_TOKEN`; their ports are not published. This checkpoint is one trusted
user per installation, not a multi-tenant authentication design.

## Client ↔ server

See `contracts/client-server.v0.schema.json`.

| Operation | Fields in addition to `v`, `op` | Reply |
|---|---|---|
| `create` | `request_id`, relative `workspace`, `mode` (`ro` / `rw`) | `session_id` |
| `message` | `session_id`, `request_id`, `text` | `session_id`, `run_id` |
| `collect` | `session_id` | Final run `results` |
| `cancel` | `session_id` | `cancelled: true` |
| `release` | `session_id` | `released: true` |

`GET /v0/events?session_id=ID&after=N` returns `text/event-stream`. Each event has
an `id` matching its `seq` and a JSON `data` field. The server returns up to four
events per connection, waiting up to 0.5 seconds when caught up. Reconnect using
the last received sequence. Repeated fetches do not repeat side effects.

`contracts/client-event.v0.schema.json` describes events. Exactly one `result`
is stored per accepted run, with outcome `success`, `error` or `cancelled`.
Terminal success means the harness finished; a BAF checker still determines task
correctness. A cancelled session is terminal; create another session to continue.

## Harness ↔ sandbox

See `contracts/harness-sandbox.v0.schema.json`.

| Operation | Fields | Behavior |
|---|---|---|
| `provision` | `session_id`, `workspace`, `mode` | Validate and reserve the mount; no idle container |
| `exec` | `session_id`, `operation_id`, `tool`, `arguments`, `timeout_s` | Run a disposable container; return one final result |
| `collect` | `session_id` | Operation result metadata, omitting output bodies |
| `cancel` | `session_id` | Mark terminal and force-remove the active container |
| `release` | `session_id` | Cancel, wait for cleanup, release the workspace reservation |

`exec` responses follow `contracts/sandbox-result.v0.schema.json`. They include
stdout, stderr, exit code, an optional error, truncation flag and duration. Output
is bounded at 64 KiB per stream. The manager has no command-output streaming
endpoint yet; this is a stated v0 limitation for Checkpoint 2.

`contracts/reply.v0.schema.json` covers other RPC responses and error envelopes.
Request bodies are limited to 1 MiB. An operation timeout must be 0.1–120 seconds;
the harness uses at most 30 seconds. Docker API calls have a 10-second socket
timeout, so daemon stalls can add bounded overhead to an operation deadline.

## Idempotency and retry policy

IDs are scoped to the running server. `create` and `message` cache their original
response; `exec` caches its terminal result. A different payload with the same ID
is rejected with HTTP 409. An in-flight duplicate exec gets `busy`; retry the
identical request after it completes. `cancel` and `release` are idempotent.
Caches and event cursors are not durable across process restarts.

| Error kind | Meaning | Retry policy |
|---|---|---|
| `command` | Nonzero command exit | Let the model inspect/correct; never blind retry |
| `validation` | Invalid schema, arguments or path | Correct the request |
| `timeout` | Execution/run budget exceeded | Inspect partial files; only a new deliberate operation |
| `sandbox` | Docker/container failure | Stop; check manager and cleanup before another operation |
| `transport` | Failed connection/HTTP response | Replay event reads; side-effect RPCs require same-ID reconciliation |
| `busy` | Active operation or reserved workspace | Retry only if `retryable` is true, or wait/release as indicated |
| `cancelled` | Session terminated | Create a new session |
| `model` | Provider failure/incomplete response | Stop the run; explicit retry only |
| `auth` | Invalid bearer token | Correct credentials |

If cancellation cannot contact the manager, the run gets a final error explaining
that cleanup could not be confirmed. It must not be reported as a clean cancellation.

## Remote folder lifecycle

No new public RPC operation is required. The SSH helper mounts the folder on the
Docker host, then calls the existing `create` with its generated `remote-<32 hex>`
workspace name. This prefix and `.remote-control` are reserved. Before provision
and during exec, the manager verifies the host helper's expiring lease and mode.
An absent or expired lease is a non-retryable `transport` failure; a disconnected
mount must be recreated as a new session. Same-host workspace requests are unchanged.

The SSH stdin control stream starts with one JSON object containing the reverse
forward port, RO/RW mode, export token and client token. Helper stdout contains JSON
`ready` (session/workspace IDs), `error`, and `closed` messages. EOF or a `close` line
requests release. Credentials are never included in stdout or lease files. File
operations use the WebDAV subset documented in [remote mounting](remote-mount.md).
