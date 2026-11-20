# Checkpoint 2 evidence

Checkpoint evidence assembled on **2026-11-19–20 UTC** from real runs.
These files contain benchmark fixtures, generated submissions, captured tool
events and result metadata, not credentials or unrelated user files.
Commands and environment are described in
[the report](../../cp2-report.md) and [measurement method](../../performance.md).

## Infrastructure evidence

- `acceptance-summary.json`: successful initial Ubuntu `make check-all CHECK_ARGS=--existing-sshd`,
  including cleanup of its temporary Compose project.
- `validation.json`: 134 offline tests from that acceptance snapshot, Python 3.12.3.
- `fedora-validation.json`: 135 tests on Python 3.14.10, including the subsequently
  added regression that rejects a mount worker which never writes new data.
- `fedora-final-validation.json`: **169 tests passed** on Fedora after the
  observation-checker and client-timeout corrections, on November 20 UTC.
- `docker-check.json`, `b6-checker.json`, `hardening.json`: actual container checks.
- `remote-mount.json`: loopback SSH/FUSE/Docker path inside the isolated acceptance
  stack on Ubuntu; not a two-machine demonstration.
- `fedora-ubuntu-mount.json`: earlier user-confirmed two-machine acceptance
  artifact, copied unchanged. Its nine checks passed; it contains no timestamp.
- `mount-performance.json`, `sandbox-performance.json`: ten successful real samples
  per metric, environment and statistical definitions; cleanup passed.
- `image-identities.json`: execution/grading image IDs and the running harness
  image ID, inspected without reading container environment.
- `cp2-manifest.json`: source hashes and fixed first-pair campaign parameters.
- `server-source-sha256.json`: 32 server runtime/client/BAF hashes, matching the
  campaign manifest.
- `replay.jsonl`: all 39 cases passing once against the isolated replay stack.
  Synthetic replay proves infrastructure/task plumbing, not LLM quality.

The corrected revision also passed a fresh Ubuntu acceptance on November 20 UTC:
**all eight steps and cleanup passed**, including **169 offline tests**. Its
`final-acceptance/summary.json`, the individual JSON reports beside it and
`final-acceptance/replay.jsonl` retain this final run separately from the initial
134-test Ubuntu snapshot and the Fedora unit suites.

## Frozen campaign and correction chain

| Artifact | Meaning |
|---|---|
| [live-cp2.jsonl](live-cp2.jsonl) | Untouched 117 original attempts from generation revision `9555ba9`: **109 passed**, 1,324,445 reported tokens; one client timeout lost its metadata |
| [live-cp2-reconciled.jsonl](live-cp2-reconciled.jsonl) | Adds verified metadata for C3 repeat 2; still **109/117**, with **1,396,935** known tokens; its failure stays failed |
| [live-cp2-reconciliation-audit.json](live-cp2-reconciliation-audit.json) | Unique missing-session/workspace evidence, original/recovered record and SHA256 links |
| [live-cp2-corrected.jsonl](live-cp2-corrected.jsonl) | Uniform post-hoc grading of 15 attempts using checker revision `ea39ddc`: **114/117**; other 102 records unchanged |
| [live-cp2-regrade-audit.json](live-cp2-regrade-audit.json) | Every verdict/field change, checker source hashes, input/event/output/snapshot hashes; zero model calls |
| [live-cp2-artifacts.json](live-cp2-artifacts.json) | Bounded UTF-8 snapshots for all 15 regraded attempts, with file and event hashes; submissions are stored as data |
| [live-cp2-events.json](live-cp2-events.json) | Full captured events for all 117 sessions, including tool output needed to reproduce observation checks |
| [live-cp2-trace-map.json](live-cp2-trace-map.json), [live-cp2-traces.jsonl](live-cp2-traces.jsonl) | Server metadata traces used to establish session identity and recover the missing C3 metadata |
| [live-cp2-original-summary.json](live-cp2-original-summary.json) | Original **verdicts** with reconciled metadata, hence 109/117 and 1,396,935 tokens |
| [live-cp2-summary.json](live-cp2-summary.json) | Corrected matrix, 114/117, repeat spread, recorded timing statistics and incomplete-usage counts |

The three remaining failures are B2.1 repeat 1 (provider error), B5.4 repeat 2
(`healthy: false` instead of integer `2`) and C3 repeat 2 (client timeout and server
cancellation). Regrading does not rerun the model or replace failed attempts.
Two runs still have uncertain provider usage: **1,396,935 is a known-token lower
bound**. C3 repeat 2 lacks client end-to-end timing, so the overall timing sample
count is **116**, and C3 timing statistics use **two** samples. Its recovered server
duration is retained separately. Historical cumulative token counters in raw rows
are preserved; summaries sum the recovered per-attempt token fields.

See [correction method and reproduction](../../evaluation-corrections.md),
[corrected matrix](../../live-results.md) and
[original-verdict matrix](../../live-results-original.md).

## Separate client-fix follow-up

The corrected client was tested on three new C3 attempts: **3/3 passed**,
**110,594 reported tokens**, under the distinct pair label ending
`client900-followup`. The published follow-up set is `live-c3-followup.jsonl`,
`live-c3-followup-events.json`, `c3-followup-manifest.json` and
`c3-followup-summary.json`. It records revision
`ea39ddc` and the 900-second client wait. These attempts are separate evidence;
they are not appended to the 117-attempt matrix or substituted for C3 repeat 2.

Only the replay JSONL artifacts have workspace paths reduced to fixture basenames. Published
live campaign, reconciliation, corrected records, events and audits are byte-exact
copies of their generated originals under ignored `results/`, preserving the
recorded hash chain. GitHub Actions has not been run for this unpublished change;
the acceptance evidence here comes from local and VM runs.
