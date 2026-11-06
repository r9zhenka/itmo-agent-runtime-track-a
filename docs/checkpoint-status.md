# Checkpoint status

| Checkpoint 1 target | Implementation | Evidence / remaining verification |
|---|---|---|
| Compose starts server | Four source-built services, sandbox image, healthchecks, `.env` initializer | Compose config validates; daemon access prevented a local build/start |
| Harness executes sandbox commands | Docker Engine adapter; per-operation containers; three tools | Local fixture executor tests pass; real Docker check command and CI job supplied |
| Protocols v0 | Request, reply, event and result JSON Schemas; auth; validation; retry semantics | Offline HTTP and contract tests |
| Client connects | Native Tk GUI and CLI share API; selection, send, events, cancel, reconnect | CLI tests pass; GUI requires manual display test |
| Initial ADRs | Seven architecture decisions plus provisional evaluation ADR | Documents in `docs/adr/` |
| BAF runner; B1–B5 | Fifteen generated fixtures, checkers, replay and live adapter | All replay tasks pass locally; real-model evaluation not run |

## Checkpoint 2 work

- Implement remote client-folder mounting, likely reverse SSH tunnel + SSHFS;
  test on two machines. Same-host bind mounting is only a Checkpoint 1 staging point.
- Exercise CPU, memory, PIDs and disk limits adversarially; currently Docker limits
  are configured, `/tmp` is bounded, but the host-mounted workspace has **no disk quota**.
- Harden permissions and symlink/concurrent-host-edit races. A read-only bind of
  an existing top-level `.git` protects it; nested repositories and `.git` created
  after provisioning are not a complete protected-file policy.
- Test malicious commands, mount/network loss, manager/harness crashes and recovery.
  Manager restart cleans its labelled containers. If the manager crashes while a
  command runs, there is no independent command watchdog yet; the command may keep
  running until cleanup. Automatic idle session expiry is also not implemented.
- Add fine-grained command-output streaming to the sandbox protocol and durable
  event/session storage if required. Current event replay survives client reconnects,
  not service restarts.
- Introduce remote transport security and multi-user session ownership before
  exposing the gateway beyond loopback. HTTP and a single shared user token suffice
  only for this local checkpoint setup.
- Add B6–B8, composites, student-original tasks and the additional BAF.
- Add filesystem/sandbox latency measurements, raw results and statistical summaries.

## Checkpoint 3 work

- Run the full basis and composites on the required model/harness pairs.
- Record model eligibility, versions, Intelligence Index and verification date.
- Analyze the matrix and basis property; replace the provisional pair-selection ADR
  with an evidence-based decision; prepare the defense.

Do not present configuration-only tests, synthetic replay, or unexecuted CI jobs
as evidence of real isolation or model quality.
