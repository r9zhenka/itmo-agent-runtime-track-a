# Evidence for checkpoint 2 fixes

Code revision: `b117d62` (runtime fixes began in `0366b1c`). These artifacts supplement the frozen original
[CP2 campaign](../cp2/README.md); they do not replace its failed attempts or change
its 114/117 corrected score. See [fixes and limits](../../cp2-fixes.md).

- `source-manifest.json`: final source hashes, code commit and recording provenance.
- `cp2-fixes-source.json`: earlier uncommitted capture-time source snapshot; it
  precedes the portable-context addition and is not the final acceptance manifest.
- `fedora-validation.json`: 225 offline tests, zero failures/errors/skips.
- `provider-record-smoke.jsonl`: nine fresh live smoke attempts, all passed,
  70,840 reported tokens. This is a separate fixture-recording campaign.
- `provider-record-events.json`: full events for those nine sessions, exported
  before removing the isolated recording stack.
- `recorded-audit.json`: audit of nine complete recordings and actual model identity.
- `recorded-context-portability-audit.json`: data-only verification of all 46
  original request-context hashes and replay with changed incidental ls metadata.
  This audit executes neither candidate code nor network calls.

The actual provider responses live in `baf/recordings/B*.json` in the repository.
They remain byte-identical to the original captures. The adjacent `*.context.json`
sidecars bind raw recording SHA256, captured-event SHA256 and verified original
context hashes. Versioned normalization ignores only explicit runtime metadata,
unittest elapsed time and parsed leading `ls -la /work` listing metadata. Names,
entry types, regular-file sizes, listing order, following output and error/status fields
remain significant. `project-a-observation-v2` additionally sorts only the three
grep records of the exact B2.1 compound command and the two find paths of the exact
B9.1 command, gated by exact task prompts and record grammar/cardinality. It
preserves membership, multiplicity, file contents and status. This addresses
filesystem enumeration differences reproduced in actual Docker, not arbitrary
changed observations. See `recorded-enumeration-diagnostic.json` and the 46-frame
`recorded-context-v2-audit.json`. The earlier portability audit covers v1 only. `scripts.derive_recorded_contexts --check` reconstructs and
verifies the sidecars from public fixed-fixture evidence without model calls.

The intermediate failed controller probe is preserved under `intermediate-failure/`: its fixture was incorrectly private (0700) for a capability-dropped controller. The test-only correction is `b37dedd`.

`recording-portability-failure/` preserves the next attempt: 13 of 14 steps passed, including both real controller SIGKILL scenarios; recorded smoke passed 7/9 and rejected B2.1/B9.1 context mismatches. Cleanup passed. Neither failed attempt is claimed as complete acceptance.

The final frozen-source Ubuntu acceptance passed all **14/14 steps**, including
225 offline tests, 39/39 synthetic cases, 9/9 recorded smoke cases, real SSH/FUSE,
helper/controller SIGKILL and cleanup. See [ubuntu/summary.json](ubuntu/summary.json)
and its [artifacts](ubuntu/artifacts/). SHA256 of all 119 source files matched
the local manifest before completion. Benchmark JSONL publication changes only
the `workspace` field to its basename; statuses, timings and observations are
preserved. Fixed-fixture live capture files above remain byte-identical. An old
successful GitHub Actions run for `64ea82a` is not proof for these unpushed fixes.
Recordings and benchmark events contain fixed teaching fixtures and model-generated
submissions, not API keys or unrelated user files. Never import submitted code on
the host to inspect these artifacts.

[Deployment check](ubuntu-deployment.json): all five main Ubuntu services healthy,
LLM mode remains live, deployed observation-normalizer hash matches the source,
and no disposable test stack or execution containers remain. This health check
does not make a fresh provider request.
