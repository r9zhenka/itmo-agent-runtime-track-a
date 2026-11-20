# Checkpoint 2 report

This checkpoint adds the two-machine filesystem path, resource/failure hardening,
the complete 39-task benchmark, offline acceptance orchestration and measurements.
The first live pair is the custom harness with
`deepseek-ai/DeepSeek-V4.1-Flash-1017`. Historical implementation-stage checks remain
in [validation history](report.md).

## Environment and reproducibility

The client is Fedora (Python 3.14.10, kernel `7.3.3-100.fc43.x86_64`, eight logical
CPUs, 15,710,344 KiB reported RAM). The server is an Ubuntu VM (Python 3.12.3,
kernel `6.8.0-139-generic`, two virtual CPUs, 4,009,872 KiB reported RAM). Client
and server have separate kernels and filesystems on one physical machine.
Execution and code-grading images use Python 3.12.10 on slim Bookworm.

The client exports fresh fixtures through WebDAV over reverse SSH. The server's
rclone 1.68.2 mounts them using FUSE; disposable Docker containers receive that
mount at `/work`. Code grading runs in separate read-only Docker containers on
the Fedora benchmark host after releasing the agent's session. Expected answers
stay outside the agent and grader containers. No generated Python is imported
by the benchmark host.

The live endpoint is reached by the LLM proxy through an explicitly mounted Unix
socket and SSH HTTP CONNECT forwarding to the client's proxy. TLS verification
remains end to end. The mount helper and execution containers receive no provider
key. See [provider transport ADR](adr/0009-provider-transport.md).

Infrastructure measurements run separately from model campaigns. Cached images
and warm filesystem caches are stated explicitly; the local filesystem baseline
runs on Fedora and the mounted measurements on Ubuntu. This is not a controlled
same-hardware comparison. Memory numbers are cgroup usage, including charged file
cache, not the whole Docker daemon's incremental host cost.

## Acceptance evidence

`make check-all CHECK_ARGS="--existing-sshd --output results/check-all-final"`
**passed on Ubuntu** on the final code revision `ea39ddc`, including teardown
of the temporary stack. [Final acceptance](evidence/cp2/final-acceptance/summary.json)
and [raw artifacts](evidence/cp2/README.md) retain these checks:

| Check | Result |
|---|---|
| Offline unit/CLI/HTTP | 169 passed on Ubuntu and 169 on Fedora; zero failures, errors or skips |
| Docker isolation/cancel/cleanup | Passed, including bounded tmpfs and process-tree cancellation |
| Independent code grader | Passed correct candidates; rejected wrong/forged results, writes and timeouts |
| Adversarial hardening | 10/10 checks passed, including CPU/RAM/PIDs, quota, canary, network and controller crashes |
| Full real-Docker synthetic benchmark | 39/39 tasks passed |
| Real rclone WebDAV | Passed reads/writes, rename/delete, client edits and RO/protected paths |
| SSH/FUSE/Docker | Nine checks passed, including disconnect cleanup and preserved client files |

The initial acceptance snapshot (134 Ubuntu tests, followed by 135 Fedora tests)
is also retained, distinct from the final 169-test checks on both machines. Added
regressions cover mount measurements, observation checks, metadata recovery and
audited regrading. The earlier user-run Fedora-to-Ubuntu acceptance also has nine
passing checks; the user demonstrated GUI output appearing in the client folder.
Automated UI coverage uses the headless client.

The first expanded acceptance exposed a quoting error in the CPU probe; it was
fixed and covered by a compile regression. Concurrent manager/watchdog removal
also needed a bounded retry for Docker's HTTP 409. The successful acceptance above
uses these fixes. CPU stress uses a reduced 0.25-CPU test quota; the production
one-CPU configuration is checked separately. File-size stress similarly tightens
the limit to 1 MiB, while the production per-file bound is 128 MiB.

The GitHub workflow runs the same acceptance command after preparing cached
images, pinned rclone, SSH and FUSE. Its remote execution requires a push; local
or VM results must not be described as a successful GitHub Actions run.

## Measured performance

Ten repeats per metric; values below are milliseconds (median / nearest-rank p95).
At n=10 this p95 is the largest sample, not a high-confidence tail estimate.

| Filesystem operation | Local Fedora | Mounted on Ubuntu |
|---|---:|---:|
| Single stat | 0.019 / 0.024 | 37.260 / 40.316 |
| Traverse fixture tree | 1.402 / 1.442 | 438.870 / 483.195 |
| Read 32 × 4 KiB files (whole batch) | 0.314 / 0.342 | 1735.387 / 1755.757 |
| Read 4 MiB | 2.178 / 2.249 | 64.104 / 85.928 |
| Write and close 1 MiB | 0.757 / 0.805 | 36.055 / 38.926 |

The serial small-file workload exposes repeated WebDAV/FUSE/SSH round trips.
Caching is deliberately limited to keep local edits visible. These data identify
a performance cost; they do not isolate network cost from VM and host differences.
The last remote write was verified in the client directory; release and cleanup passed.

| Sandbox measurement | Median | p95 |
|---|---:|---:|
| Cached-image container start, ms | 435.349 | 642.509 |
| Complete operation lifecycle, ms | 601.831 | 741.111 |
| Host Python process baseline, ms | 28.873 | 42.097 |
| Lifecycle minus host baseline, ms | 572.301 | 699.290 |
| Idle sleep cgroup, MiB | 0.551 | 0.699 |
| Idle Python cgroup, MiB | 4.309 | 4.383 |
| Python minus sleep cgroup, MiB | 3.760 | 3.840 |

The host process uses Python 3.12.3 and the container uses 3.12.10, so the time
difference also includes interpreter-build differences. The cgroup difference
measures this workload increment, not all isolation overhead.
All measurements completed successfully and removed their containers/mounts.
Raw samples and exact definitions: [mount](evidence/cp2/mount-performance.json),
[sandbox](evidence/cp2/sandbox-performance.json), [method](performance.md).

## First-pair experiment

There are 39 tasks: 24 course tasks, eight original variants, three tasks for the
new style-following B9, and four composites. Three attempts per task use fresh
workspaces and sessions. The campaign fixes source hashes, limits, model identity
and configuration before starting. The implementation was committed locally as
`9555ba9`; its source bytes match the pre-run manifest. Provider defaults other than `max_tokens=2048`
remain unchanged; reasoning effort is not independently verified.
See [model eligibility](model-eligibility.md) and
[evaluation ADR](adr/0008-evaluation.md).

Every failed attempt stays in the denominator. Provider failures with missing
usage make the reported token sum a lower bound; a conservative per-run budget
reservation prevents treating failed calls as free. Pilot/debug runs are stored
separately and never replace scored attempts. The one-pair matrix describes a
baseline; it does not select a winner among harness/model combinations.

## First-pair results and corrections

The campaign completed **117/117 attempts** on November 19–20, 2026 (UTC), using
three concurrent sessions. Original verdicts were **109/117 (93.2%)**. Uniform
observation regrading gives **114/117 (97.4%)**. See the
[corrected matrix](live-results.md), [original verdict matrix](live-results-original.md)
and [correction/reconciliation method](evaluation-corrections.md).

The five corrected false failures came from stream/capture interpretation, not
new model attempts. All 15 affected attempts were regraded, including original
passes; 102 were untouched. Original evidence is retained, and runtime failures
cannot become successes merely because their final files look correct.

| Remaining failure | What the evidence establishes |
|---|---|
| B2.1, repeat 1 | The model stage rejected a failed/invalid completion. The generic provider error does not distinguish the precise cause; usage is incomplete. |
| B5.4, repeat 2 | The observed probe reported a healthy replica count of `2`; the answer incorrectly used `false`. Input/type checks still reject it. |
| C3, repeat 2 | The old client watcher stopped at 210 seconds while the server allowed 600, then cancelled the run. Verified metadata were recovered; the failed outcome is preserved. |

Per-repeat scores are **38/39, 37/39 and 39/39**. Population standard deviation
across these three rates is **2.1 percentage points**, range **5.1 points**; this
small fixed sample is not a general confidence claim. The metadata-reconciled
reported token subtotal is **1,396,935**; **two attempts have incomplete usage**,
so it is a lower bound, not an exact bill. The campaign's conservative budget
counter ended at **9,321,052**, including reservations for unreported usage;
reservations are not billed-token measurements. The authorized upper limit was
100 million tokens.

Original recorded attempt duration has median **47.374 s**, p95 **107.660 s**,
with **n=116**. C3 repeat 2 lost its client duration; its server cancellation was
at **210.433 s** and is reported separately. The duration summary therefore
covers the 116 recorded attempts, not an unbiased tail estimate for all 117.
Regrading costs are separate and do not alter original generation/duration fields.

The fixed client uses a 900-second watch limit and preserves partial evidence on
errors. A [three-attempt C3 follow-up](c3-followup.md) on revision `ea39ddc`
passed **3/3**, including 17 hidden vectors each, with **110,594 reported tokens**.
It never replaces the timed-out original attempt. It overlapped the final offline
acceptance run, so its timings are not a controlled performance comparison with
the baseline. All follow-up generation phases finished before 210 seconds, so
these new attempts alone do not isolate the causal effect of the longer timeout.

All basis groups and composites have complete coverage on this first pair.
The remaining C3 failure is a client lifecycle failure, so it is not evidence
that a correctly executed composition necessarily defeats otherwise successful
basis functions. One pair and three repetitions do not establish the general
basis property or a best harness/model combination.

## Remaining scope

The broader project still needs additional pairs, comparative basis/composite
analysis, a final pair-selection ADR and the defense. A-6.2's dedicated
sandbox-to-harness event stream is also not implemented: each sandbox `exec`
returns one bounded terminal response, while the client receives progress events
from the harness. Full A-6 compliance is not claimed.

This is a trusted single-user installation. Docker socket access in the manager
and watchdog is host-root authority; both services, the host clock and kernel
remain trusted. Simultaneous loss of both controllers or Docker can delay cleanup.
Remote writes have a logical 256 MiB / 4096-entry quota; a trusted local editor
is outside it. Direct local RW binds require an explicit development opt-in and
have no aggregate quota. There is no distributed edit lock, durable session
recovery or automatic idle-session expiry. FUSE semantics and manual cleanup
after a host/helper SIGKILL are documented in [remote mounting](remote-mount.md).
