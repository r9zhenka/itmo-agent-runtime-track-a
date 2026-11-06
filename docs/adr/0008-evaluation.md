# 0008 — Evaluation modes and deferred pair selection

Status: provisional; no quality-based pair selection has been made.

## Decision

Use synthetic replay for deterministic, offline runtime tests. Implement a separate
live provider mode that receives the same prompts and tool interfaces. Record
provider/model identity separately from a user-supplied pair label. Never count
synthetic replay as model-quality evidence.

## Alternatives

- Live model calls on every CI run: tests model behavior, but adds cost, network
  availability and nondeterminism to basic infrastructure checks.
- Record/replay actual provider responses: stronger provenance than synthetic
  fixtures, but requires an initial authorized live campaign and careful handling
  of recorded content. A useful later addition.

## Consequences

Checkpoint 1 can validate B1–B5 task plumbing without credentials. To choose a
pair, run all required tasks and repetitions on course-eligible models, record
versions/index/date, compare success rates, time and tokens, and supersede this ADR
with the resulting evidence. Only one custom harness is currently implemented.
