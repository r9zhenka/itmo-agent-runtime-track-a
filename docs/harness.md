# Harness walkthrough

The custom harness is `runtime/harness.py`. It never imports `subprocess` or the
Docker adapter. All tool execution goes through the sandbox RPC client.

## Loop and stopping

`Harness.message` accepts an idempotent request, appends the user message to the
session conversation, emits `started`, and launches `Harness.run` on a worker
thread. One run is allowed per session. `Harness.run` calls the proxy, appends its
assistant message, executes each requested tool sequentially, and appends each
tool result with the corresponding `tool_call_id`.

The loop stops on an assistant response without tool calls, cancellation, a
critical sandbox/transport error, the 16-step limit, the configured run budget, or
a 180,000-character serialized context limit. The run deadline is checked between
bounded RPCs; a blocked RPC can delay termination up to its transport timeout.
It is not a real-time deadline. `Harness.finish` guards the final result under a
lock, so cancellation and normal completion cannot emit two final results.
Once cancellation starts, the cancel path owns terminal publication and waits
for confirmed sandbox cleanup. A racing worker cannot publish clean cancellation
before that acknowledgement; failed cleanup produces an explicit terminal error.
The deployed default is `RUN_TIMEOUT=600` seconds; direct test constructors retain
a 180-second default. Provider requests have `LLM_TIMEOUT=90` seconds (maximum
120); the harness-to-proxy HTTP timeout is 125 seconds. The client watches a run
for up to 900 seconds. The old 210-second client limit cancelled one C3 benchmark
attempt prematurely; the correction and retained failure are documented in
[evaluation corrections](evaluation-corrections.md). Benchmark errors now retain
partial events, identifiers and known usage instead of discarding their evidence.

## Tool dispatch and errors

`runtime/contracts.py:TOOLS` defines `RunCommand`, `ReadFile`, and `WriteFile`.
`tool_definitions()` supplies their schemas to the model. `Harness.run` checks the
tool name and validates parsed JSON arguments before calling the manager. The
operation ID is derived from run, step and call index.

Production `Remote.execute` submits asynchronous sandbox `start`, then long-polls
ordered `events` from its returned cursor. `started` and `running` become client
`tool_progress`; a terminal sandbox `result` supplies one `tool_result`. Repeated
event reads do not reexecute work. Blocking `exec` remains for compatible adapters.

`RunCommand` uses a shell inside a new container. File tools run
`runtime/file_tool.py` inside the same kind of container. File paths must resolve
inside `/work`; `.git` is prohibited. UTF-8 reads and writes are bounded to 64 KiB.
For byte-preserving operations the model can use a Python command inside the
sandbox, as in B4.3.

Command failures and argument errors are returned to the model so it can correct
them. Timeout, cancellation, sandbox and transport errors stop the run. A failed
transport request may have executed a side effect, so the harness does not
automatically try the command again. An explicit same-ID RPC retry can obtain the
manager's cached result while its process remains alive.

## Context and model selection

The conversation starts with `SYSTEM`, followed by user, assistant, and tool
messages. It persists across messages in a session. Nothing is silently truncated;
oversized context fails with a clear error. Advanced context compression is outside
this checkpoint.

`LLM_MODE`, `LLM_PROVIDER_URL`, `LLM_MODEL`, and `LLM_EXTRA_JSON` configure the proxy.
`LLM_URL` and `SANDBOX_URL` configure the harness service endpoints. The gateway's
`HARNESS_URL` can point at a replacement harness implementing the same protocol.
Only one harness implementation is included at this checkpoint.

## Events and observability

`Harness.emit` maintains an ordered, in-memory event log. The gateway returns SSE
batches, and clients reconnect with a cursor. Tool stdout/stderr are available at
operation completion; this version does not stream individual output chunks or
model tokens. `started`, `model`, `tool_start`, `tool_progress`, `tool_result` and one final `result`
make progress visible during a run.

JSONL traces preserve identifiers, tool names, durations, outcomes, model identity
and token counts. They omit prompts and file contents. Full event history lasts
only for the server process lifetime and retained sessions. Capacity is 128 active
harness sessions, 16 runs per session and 256 operations per sandbox session.
Closed sessions are trimmed to a retention target of 128 on a new create, together
with their create-request cache entries. This fixes exhaustion after 128 sequential
released sessions; it does not add durable recovery or automatic idle expiry.
The manager independently allows 512 active sessions and trims old released
sessions to a 128-entry retention target on provisioning.

Gateway ownership checks protect both RPC and SSE access for configured token
principals. The harness is reached only through the trusted internal-token boundary;
OS workspace ownership and SSH users are not derived from those principals.
See [the diagrams](cp2-architecture.md) and
[successful/cancelled real traces](cp2-trace-walkthrough.md). The historical
`9555ba9` campaign did not yet emit `tool_progress` and used the older client limit.
