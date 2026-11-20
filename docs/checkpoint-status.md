# Checkpoint status

## Current implementation and evidence

Runtime revision `0366b1c`, test-only fix `b37dedd` and recorded-context
portability fix `b117d62` contain changes after published revision `64ea82a`.
**Final Ubuntu acceptance passed all 14 steps and cleanup**, with 225 offline
tests, 39/39 synthetic BAF and 9/9 recorded smoke. It used an unchanged `b117d62`
copy, with all 119 frozen source hashes matching. See the
[Ubuntu summary](evidence/cp2-fixes/ubuntu/summary.json) and
[raw artifacts](evidence/cp2-fixes/ubuntu/artifacts/).
Fedora also passed 225 offline tests in 50.758 s
([report](evidence/cp2-fixes/fedora-validation.json)). Nine separate actual-provider
smoke captures passed, reporting 70,840 tokens. Historical failures remain in the
[fixes report](cp2-fixes.md); the old GitHub run does not validate these newer,
not-yet-pushed changes.

| Area | Implementation | Evidence / remaining verification |
|---|---|---|
| Server and harness | Four source-built HTTP services, custom tool loop, disposable command containers and independent watchdog | Current Fedora/Ubuntu 225 tests passed; Ubuntu all 14 acceptance steps and cleanup passed ([evidence](evidence/cp2-fixes/ubuntu/summary.json)) |
| Protocols and client | Named-token session ownership; sandbox start/events with progress and exactly one result; GUI/CLI | Owner/progress/cancel/disconnect regressions passed within 225; full real-stack acceptance, synthetic39 and recorded9 passed |
| Two-machine mounting | Client WebDAV over SSH, pinned rclone/FUSE, independent host mount guard, parent/child export locks and optimistic version checks | Fedora → Ubuntu nine-check acceptance and new helper-SIGKILL three-check probe passed; included in final full suite |
| Isolation and allocation | Non-root/networkless command containers, resource limits, remote export quota of 256 MiB / 4096 entries | Eight real resource/quota checks and separate actual Compose controller-crash checks passed; historical manual-reaper probes remain separately labelled |
| Failure handling | Manager timeout plus independent watchdog using immutable deadline labels and remote leases; no automatic operation replay after transport failure | Individual process-loss handling implemented; no timely-cleanup guarantee if Docker or both privileged control-plane services are unavailable |
| BAF basis and composites | 39 tasks: 24 course B1–B8, eight original variants, three B9 tasks and C1–C4 | Deterministic fixtures/replay and independent checkers implemented; generated-code tasks have 53 hidden vectors in an isolated grader |
| Live model | HTTPS provider adapter, optional explicit proxy or SSH Unix-socket HTTP CONNECT route | Complete first pair: 114/117 after audited checker corrections, original 109/117 retained; separate C3 follow-up 3/3 ([results](live-results.md)) |
| Performance | Mounted-filesystem and Docker lifecycle/resource scripts with raw samples and median/p95 summaries | Ten repeats per metric completed; raw samples and median/p95 in [report](cp2-report.md#measured-performance) |
| Architecture | Nine ADRs covering harness, isolation, transport, mounting, sessions, evaluation and provider connectivity | Pair selection remains provisional pending the required comparative evidence |

The original CP1 milestone delivered the client/server skeleton, contracts, Docker
execution and B1–B5 replay. At that stage this environment lacked Docker access;
that historical limitation should not be confused with the later user-confirmed
Ubuntu VM acceptance. Configuration assertions and synthetic replay still do not
establish real isolation or model quality.

## Checkpoint 2 completion

- All 39 × 3 live attempts are recorded, including failures. Coverage, success
  rates, repeat variability, timings and token uncertainty are in the report.
- All affected checker observations were uniformly regraded without new model
  calls. Original records, recovered metadata and correction audits are retained.
- Historical offline, Docker, hardening and SSH/FUSE acceptance passed on Ubuntu.
  These refer to the historical `ea39ddc`/`64ea82a` evidence, including 169 tests.
- Published revision `64ea82a` also passed both GitHub Actions jobs in
  [run 44693131644](https://github.com/r9zhenka/itmo-agent-runtime-track-a/actions/runs/44693131644).
  This is not a CI result for the later local corrections through `b117d62`.
- Reports and ADRs describe the measured first pair and remaining limitations;
  they do not claim a comparative winner or full-project completion.

See [BAF design](baf.md), [original variants and composites](baf-additions.md),
[hardening boundaries](hardening.md), [remote mounting](remote-mount.md), and
[acceptance/measurement commands](performance.md).
For the checkpoint discussion use the [detailed architecture](cp2-architecture.md),
[annotated real traces](cp2-trace-walkthrough.md), and
[question-by-question answers](checkpoint-2-answers.md).

## Corrections after the checkpoint-question audit

- Gateway checks configured token principals against each session owner, including
  event reads, and scopes create-request IDs to that identity. Redirects are rejected.
- Active-session capacity is separate from closed retention: 128 active in harness,
  512 in manager, with a 128-closed retention target pruned on new create/provision.
- Sandbox `start`/`events` and optional SSE expose started/running/result; the harness
  forwards `tool_progress`. Blocking exec remains for compatibility; stdout/stderr
  chunks and model-token streaming are not implemented.
- Cancellation terminal publication is owned by the path that confirms cleanup,
  preventing a competing worker from declaring clean cancellation prematurely.
- A separate host mount guard owns rclone/FUSE and handles SSH-helper pipe EOF,
  including helper SIGKILL. Export locks reject parent/child overlaps; mutation
  version/ETag checks reduce concurrent-edit conflicts.
- `scripts.check_watchdog_crash` now kills real controllers only in a verified
  disposable Compose project. The manager-loss case requires a deadline-removal
  log from the separate production watchdog; the test does not call the reaper.
  `scripts.check_mount_crash` separately exercises helper-SIGKILL/FUSE cleanup.

The final 225-test Fedora/Ubuntu suites, helper-crash probe and both actual Compose
controller-crash scenarios passed. The earlier fixture-permission failure and
recorded-smoke 7/9 failure are retained in
[intermediate-failure](evidence/cp2-fixes/intermediate-failure/) and
[recording-portability-failure](evidence/cp2-fixes/recording-portability-failure/).
After `b117d62`, a new unchanged checkout passed the complete suite, including
recorded smoke 9/9. Nine actual-provider smoke
recordings are complete and pass (70,840 reported tokens), with nine hash-bound
`project-a-observation-v2` sidecars. All 46 original context hashes were verified
before derivation; replay ignores specified ls metadata and, only for exact
task/command pairs, sorts three B2.1 grep records or two B9.1 find paths. Names,
contents, file sizes, membership, multiplicity, remaining order/output and errors
stay significant. Raw recordings remain byte-identical. `derive_recorded_contexts --check` runs in CI; see [details](cp2-fixes.md#recorded-smoke).
The old 117-attempt model campaign is not rerun or relabelled as an experiment on
the new runtime.

## Scope and remaining limitations

The primary remote exporter enforces logical content/entry bounds, not an OS quota
on the client's user. Trusted local edits can independently grow a folder. Direct
local RW binds have no aggregate quota and require explicit `ALLOW_LOCAL_RW=1`;
runtime/Compose default to `0`, while `.env.example` opts in for local development.
Read-only grader snapshots do not require that opt-in.

The manager and watchdog both have Docker-socket authority. Execution containers
receive neither that socket, SSH credentials nor provider keys. Both services and
the host clock remain trusted; this is not kernel isolation or multi-tenant
hosting. Remote `.git` protection covers all depths; direct local binds retain the
more limited existing top-level `.git` protection.

Remote filesystems support whole-file writes, not full POSIX append/random-write,
permission or Git semantics. Optimistic mutation checks leave a final race against
local editors; they are not a distributed lock. Guard SIGKILL or whole-host failure
can leave FUSE resources needing explicit cleanup, even though helper SIGKILL now
has a separate cleanup owner. There is no automatic idle-session expiry or durable
conversation recovery. Event reconnect never reexecutes an ambiguous operation;
evicted closed sessions and restarted services lose their in-memory replay window.

## Checkpoint 3 work

- Run the required model/harness comparison matrix and basis-property analysis.
- Repeat [model eligibility verification](model-eligibility.md) for each additional
  model; the first pair was verified on 2026-11-19.
- Replace the provisional pair-selection decision with comparative evidence and
  prepare the defense.

Do not present unexecuted CI jobs, configuration tests, synthetic replay or a
single successful pilot as evidence of full isolation or model quality.
