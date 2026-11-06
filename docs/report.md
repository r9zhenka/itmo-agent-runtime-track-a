# Checkpoint 1 validation report

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
