# Checkpoint status

## Current implementation and evidence

| Area | Implementation | Evidence / remaining verification |
|---|---|---|
| Server and harness | Four source-built HTTP services, custom tool loop, disposable command containers and independent watchdog | 169 tests passed on each of Fedora and Ubuntu; full Ubuntu `make check-all` passed ([evidence](cp2-report.md)) |
| Protocols and client | Versioned JSON contracts, authenticated HTTP, resumable events, GUI and CLI | User confirmed the GUI remote connection and client-visible output; in-memory events do not survive service restart |
| Two-machine mounting | Client WebDAV over SSH, pinned rclone/FUSE on Ubuntu, Docker bind of the live mount | Fedora → Ubuntu VM acceptance completed: nine passing checks in `results/remote-mount.json`, including RO, bidirectional visibility and disconnect cleanup |
| Isolation and allocation | Non-root/networkless command containers, resource limits, remote export quota of 256 MiB / 4096 entries | 10/10 real adversarial checks passed, including resource exhaustion and controller crashes |
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
- Final offline, Docker, hardening and SSH/FUSE acceptance passed on Ubuntu.
  The GitHub Actions workflow is prepared but its run awaits publication.
- Reports and ADRs describe the measured first pair and remaining limitations;
  they do not claim a comparative winner or full-project completion.

See [BAF design](baf.md), [original variants and composites](baf-additions.md),
[hardening boundaries](hardening.md), [remote mounting](remote-mount.md), and
[acceptance/measurement commands](performance.md).

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
permission or Git semantics. Concurrent local edits lack a distributed lock.
Host/helper SIGKILL can leave FUSE resources needing explicit cleanup. There is no
automatic idle-session expiry or durable conversation recovery. The dedicated
sandbox-to-harness event stream required by broader A-6.2 remains unimplemented:
sandbox exec returns one bounded terminal response, and the harness provides the
client's progress events. Event reconnect never reexecutes an ambiguous operation.

## Checkpoint 3 work

- Run the required model/harness comparison matrix and basis-property analysis.
- Repeat [model eligibility verification](model-eligibility.md) for each additional
  model; the first pair was verified on 2026-11-19.
- Replace the provisional pair-selection decision with comparative evidence and
  prepare the defense.

Do not present unexecuted CI jobs, configuration tests, synthetic replay or a
single successful pilot as evidence of full isolation or model quality.
