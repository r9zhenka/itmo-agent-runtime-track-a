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
critical sandbox/transport error, the 16-step limit, the 180-second run budget, or
a 180,000-character serialized context limit. The run deadline is checked between
bounded RPCs; a blocked RPC can delay termination up to its transport timeout.
It is not a real-time deadline. `Harness.finish` guards the final result under a
lock, so cancellation and normal completion cannot emit two final results.

## Tool dispatch and errors

`runtime/contracts.py:TOOLS` defines `RunCommand`, `ReadFile`, and `WriteFile`.
`tool_definitions()` supplies their schemas to the model. `Harness.run` checks the
tool name and validates parsed JSON arguments before calling the manager. The
operation ID is derived from run, step and call index.

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
model tokens. `started`, `model`, `tool_start`, `tool_result` and one final `result`
make progress visible during a run.

JSONL traces preserve identifiers, tool names, durations, outcomes, model identity
and token counts. They omit prompts and file contents. Full event history lasts
only for the server process lifetime. Capacity limits are 128 sessions per harness,
16 runs per session, and 256 operations per sandbox session.
