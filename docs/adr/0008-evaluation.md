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

## B6 grading extension

Code-generation checks use expected outputs held outside a separate Docker
container, rather than trusting public test logs or executing a submitted module
on the evaluator host. Each input uses a fresh process/container and a read-only
snapshot after releasing the agent session. The task fails if Docker is unavailable.
Offline tests can explicitly inject a fixture executor for known test code, with
distinct backend provenance. See [B6 grading](../baf.md#b6-code-generation).

## Checkpoint 2 experiment policy

The first live pair is `custom+deepseek-v4.1-flash-1017`; exact provider identity,
eligibility and index verification are in [model eligibility](../model-eligibility.md).
All 39 registered tasks receive three fresh-workspace attempts. Each model call
uses the same tool schemas and limits; the independent grader cannot be queried
by the model. Source hashes and configuration are frozen before the campaign.

Keep every failed attempt, including provider/transport failures, in the matrix.
The summarizer rejects duplicate attempts, mixed replay/live records and changes
of model within a pair. Unknown usage is reported as unknown; known token totals
are a lower bound when a provider request fails. Budget reservations constrain
concurrent requests. Pilot runs are kept separately and never substituted for a
failed scored attempt.

The first campaign completed 117 attempts: 109 original passes, 114 after
uniform regrading of 15 observations using corrected checkers. The other 102
records and all runtime failures were preserved. A separate C3 follow-up passed
3/3 after correcting the client watch timeout. Raw records, correction audit,
token uncertainty and timings are linked from the [CP2 report](../cp2-report.md).

One pair supports a baseline, not a comparative choice. This ADR remains
provisional until additional pairs and composite/basis results support a decision.
