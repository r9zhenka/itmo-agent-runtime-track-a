# 0001 — Custom Python harness

Status: accepted for Checkpoint 1.

## Context

The defense requires explaining the agent loop, context construction, dispatch and
error handling. The checkpoint should be understandable without learning a large
framework's internal lifecycle.

## Decision

Implement a small bounded tool-calling loop in `runtime/harness.py`. Keep provider
access behind an HTTP proxy and tool execution behind the sandbox protocol.
Python 3.12's standard library is sufficient for this checkpoint; no third-party
runtime packages or lockfile are required. The container Python version is pinned.

## Alternatives

- An existing open-source coding harness: more features, but more code to understand
  and dependencies to pin.
- A general agent workflow framework: useful for complex graphs, but unnecessary
  for the current sequential tool loop.

## Consequences

The code is easy to inspect and test. We own cancellation, context budgeting and
error behavior. Sophisticated context compression, durable recovery and provider
streaming must be implemented later. The gateway can point to another compatible
harness endpoint for later comparisons.
