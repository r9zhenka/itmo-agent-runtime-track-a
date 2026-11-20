# Validation history

The sections below preserve earlier checkpoint results and their original
limitations. Current results are in [the checkpoint-2 report](cp2-report.md). Architecture and
verification status are in [checkpoint status](checkpoint-status.md); the checkpoint-2 experiment records
the [model identity and eligibility](model-eligibility.md),
[hardening scope](hardening.md), and [measurement method](performance.md).

The implementation was developed in the course workspace on 2026-11-05.

## Locally reproducible checks

- `python3 -m scripts.validate` (equivalent to `make test-ci`): offline unit/CLI/HTTP tests, including all 15 B1–B5 synthetic
  replay cases. The command writes `results/validation.json`.
- `docker compose config --quiet`: Compose interpolation and structure validation.
- `python3 -m compileall -q runtime client baf scripts tests`: Python syntax validation.

The offline stack uses a test-only local process executor. It is not a container,
does not enforce network/resource isolation, and is never used by production.

## Checks not executed in this environment

- Compose image builds and real-container tests: the host Docker socket denied
  access; the escalated attempt also failed, and sudo required a password.
- Native GUI interaction: Tk imports successfully, but no graphical test session
  was used. Automated UI tests exercise the CLI mode.
- Paid/live model calls and model comparisons: no provider credentials were used.
- Remote two-machine mounting: implementation is deferred to Checkpoint 2.
- GitHub Actions execution: a workflow was added but no remote run was initiated.

GNU Make is not installed in the development environment; validation used the
direct Python entrypoint. The README provides direct commands for the Make shortcuts.

## Independent subagent testing

Two `gpt-6-luna` subagents independently exercised the offline suite and reviewed
runtime behavior. The initial 21 tests passed. Review reproduced a deadline bug:
a delayed Docker status response could be accepted as success after the operation
deadline. The manager now checks cancellation and the deadline after container
creation, status inspection and log collection before starting or accepting work.

The Docker check script was also hardened: executor failures and timeouts cannot
count as successful isolation checks, the root filesystem is inspected for its
read-only flag, and the temporary-disk test requires an actual out-of-space error.

The final independent rerun passed **23 tests**, including regression coverage for
these findings and all 15 synthetic BAF replay cases. Compose configuration also
validated. The subagent's escalated Docker access attempt was denied too; this
review does not add evidence of real-container isolation or live-model quality.

## Measurements and conclusions

No model-quality, mount-latency, sandbox-overhead or comparative performance
numbers are claimed. Synthetic replay establishes expected fixture outcomes and
protocol behavior only. The production benchmark runner records raw results when
run against Compose; `make test-docker` records actual Docker checks separately.

## Remote mounting implementation validation

The implementation adds a Linux client exporter, OpenSSH forwards, a pinned
rclone/FUSE host supervisor, expiring mount leases, GUI/CLI entry points and
acceptance scripts. The following checks were executed locally:

- `python3 -B -W error::ResourceWarning -m unittest discover -s tests -v`:
  **44 tests passed**, including the original suite and remote exporter, lease,
  interruption, conflict and control-process lifecycle regressions.
- `python3 -B -m scripts.check_webdav --rclone /tmp/project-a-rclone-1.68.2/rclone`:
  passed with the actual SHA256-verified rclone 1.68.2 binary. Exercises listing,
  reading, uploading (including chunked streams), rename/delete, client edits,
  protected paths and read-only mode. This test uses HTTP on loopback, not FUSE.
- Python syntax, CLI help and `git diff --check` passed. The pinned binary accepts
  the mount command flags.

The environment has no `/dev/fuse`. Full SSH/FUSE/Docker acceptance, native GUI
interaction and a two-machine demonstration were **not executed here**. The
workflow now supplies a loopback SSH/FUSE/Docker acceptance step; its outcome is
not claimed until it actually runs. `scripts.check_remote` is the corresponding
manual two-machine test. Filesystem latency measurements remain outstanding.

See [remote-mount instructions and limitations](remote-mount.md), including the
uncached VFS write restrictions and manual recovery after a host/helper crash.

## B6 code-generation implementation validation

Three B6 tasks now include specifications, public examples, synthetic replay and
23 evaluator-only inputs. The benchmark contains 18 tasks in total, with six smoke
tasks. Generated submissions are graded in separate Docker containers after the
agent session is released. Expected answers stay outside those containers.

Executed for this change:

- `python3 -B -W error::ResourceWarning -m unittest discover -s tests -v`:
  **54 tests passed**, including all 18 replay tasks through four HTTP services
  using the explicitly test-only fixture executor.
- `docker build -f sandbox.Dockerfile -t project-a-sandbox:cp1 .`: succeeded.
- `python3 -B -m scripts.check_b6`: **passed using actual Docker**. All three
  reference implementations passed their hidden inputs. Wrong answers, a forged
  pass report with process exit status 0, and attempted writes to the read-only
  submission were rejected. Network/secret isolation and timeout cleanup passed;
  every created checker container was confirmed removed. Raw evidence is in
  `results/b6-checker.json` (generated, ignored by Git).
- Python syntax and `git diff --check` passed.

Docker daemon access was available for these B6 checks, unlike the original CP1
development run. These results cover the grader and its isolation; they do not
claim a live-model evaluation, a complete Compose deployment test, or the pending
two-machine mount demonstration. The GitHub workflow includes the new Docker
grader test, but no remote workflow run was initiated by this change.

## B7 reasoning implementation validation

Three B7 tasks now cover transfer timing, role inheritance with deny precedence,
and contradictory rules with context witnesses. Each produces `answer.json`.
Independent data-only checkers derive expected results from the original fixture;
they do not trust edited input files, replay answers or agent success messages.
The current benchmark contains 21 tasks, with seven smoke tasks.

Executed for this change:

- `python3 -m unittest tests.test_reasoning_baf -v`: **11 tests passed**. Coverage
  includes boarding-time equality and midnight, transitive/diamond inheritance,
  default deny and irrelevant rules, joint-context contradictions, incomplete or
  spurious evidence, strict JSON types, duplicate keys, modified inputs, bounded
  reads and rejection of links/special files.
- `make test-ci`: **65 tests passed**, including all 21 replay tasks through the
  four HTTP services using the test-only fixture executor. The machine-readable
  validation summary is written to `results/validation.json`.

Existing CI commands automatically discover the new unit tests and BAF cases.
No remote GitHub workflow, real Docker B7 run or live-model evaluation was executed
for this change. No sandbox or runtime-protocol behavior changed for B7.

## B8 multi-source synthesis implementation validation

B8 adds quarterly sales from five CSVs, accepted decisions from ten meeting
protocols, and selection/comparison of two regulation versions. The benchmark now
contains 24 B1–B8 tasks, with eight smoke tasks. All three new tasks produce
structured `answer.json` with source evidence and use existing tools.

The sales checker derives exact totals from original CSV inputs. Meeting decisions
and regulation clause values use independent curated annotations; version
eligibility is calculated from original metadata. These fixed annotations are
fixture-specific, not a general text-understanding checker. Replay answers are
maintained separately and are not consulted during grading. B7 and B8 share a
bounded JSON reader that rejects ambiguous JSON and non-regular output files.

Executed for this change:

- `python3 -m unittest tests.test_synthesis_baf tests.test_reasoning_baf -v`:
  **22 tests passed**, including 11 new B8 regressions. They cover exact amounts,
  refunds, quarter boundaries, zero-contribution sources, unaccepted proposals,
  merged reaffirmations, absent assignments, version effective dates/status,
  incomplete differences, incorrect citations, edited inputs and invalid outputs.
- `make test-ci`: **76 tests passed**, including all 24 tasks through four local
  HTTP services with the explicitly test-only fixture executor. All B8 replay
  sequences completed within the existing step limit. Results are recorded in
  `results/validation.json`.

No real Docker B8 run, live-model evaluation or remote GitHub workflow was executed
for this change. Existing CI discovers the added tests and benchmark tasks without
new workflow steps. Sandbox behavior and runtime protocols were not changed.
Composite and student-original tasks remain outstanding for Checkpoint 2.
