# Observation-checker correction after the first campaign

The first live campaign ran on **November 19–20, 2026 UTC**, with frozen
implementation `9555ba9`. Its original 117 records are retained unchanged:
**109/117 passed**. After metadata recovery and uniform regrading with revision
`ea39ddc`, **114/117 passed**. This changes the interpretation of existing
observations; it does not rerun the original agent attempts.

During review, valid command output exposed
three mistakes in how the benchmark interpreted tool-result streams:

- B4.2, B6.4, C1 and C3 looked for unittest counts only in `stderr`. A shell can
  redirect the same successful test transcript into `stdout`.
- C3 compared the entire shell output with `3723`. A correct CLI run can be
  followed by a shell diagnostic such as `EXIT=0`; that does not change the CLI.
- B5.4 assumed the tool's exit status and streams belonged directly to `probe.py`.
  A wrapper can capture the child status and both streams, print explicit labels,
  and itself exit successfully. The captured child status is still 3.

The correction accepts complete successful unittest summaries on either stream,
and a complete `3723` stdout line with surrounding shell diagnostics. Nonzero
status, execution errors, truncation and explicit failed test summaries do not
become successful test evidence. Exact source/AST checks and hidden function
tests are unchanged.

B5.4 accepts either the direct process result or a narrowly defined capture:
`EXIT=3`, a `--- STDOUT ---` header, the fixture's two stdout lines, a
`--- STDERR ---` header and its exact warning. An optional `--- LAST STDOUT LINE ---`
section must repeat the valid JSON. Header spacing and CRLF are allowed. The
checker requires the actual JSON values/types and explicit child exit status;
reading the source, omitting the labels/status, or printing an unrelated number
does not qualify. The probe file must remain unchanged. This is observed textual
evidence, not cryptographic proof against a deliberately forged transcript.

One B5.4 attempt wrote `healthy: false` instead of the observed count `2`.
That is an actual answer error and remains a failure after correction.

## Uniform regrading

C3 repeat 2 exposed a separate client bug: the old event watcher stopped after
210 seconds although the server run budget was 600 seconds. The benchmark then
discarded partial metadata. Its unique missing session was reconciled against
117 server traces, 116 known session IDs, the unique unmapped C3 workspace and
the observed C3 specification. The server records cancellation at 210.433 seconds
and 72,490 reported tokens. These metadata are added in a separate reconciled
file; the original failed verdict/reason remain intact. No client end-to-end
duration is invented from the server duration. The reconciliation audit links
both files by SHA256; unknown in-flight usage remains unknown.

The untouched raw file reports **1,324,445 tokens**. Recovering C3 repeat 2 adds
**72,490**, producing **1,396,935 known tokens** in both reconciled and corrected
summaries. B2.1 repeat 1 and C3 repeat 2 still have uncertain usage, so this is a
lower bound. Original cumulative campaign counters are historical and remain
unchanged; summaries use the sum of the per-attempt `tokens` fields.

The fixed client waits up to 900 seconds, and future benchmark stream failures
retain partial metadata and an event cursor. Three new C3 follow-up attempts
passed **3/3**, using **110,594 reported tokens**. Their distinct
`custom+deepseek-v4.1-flash-1017-client900-followup` label and manifest identify
revision `ea39ddc`. This separate validation does not replace the original timed-out
attempt or join the original 117-attempt matrix.

All three attempts for all five affected tasks are regraded: **15 attempts**,
including originally passing attempts. The other **102 records** retain their
original values. No agent session or model request is repeated. Affected final
files are read as bounded UTF-8 data into snapshots; generated code executes only
in the independent Docker grader. Hidden tests are run even where an earlier
observation failure prevented the original grader from reaching them.

The regrade command validates the complete 39 × 3 campaign, exact event coverage,
session/trace identity, event order, one terminal result, model identity and token
counts before grading. Runtime/model error outcomes remain failures. Original
generation times, durations and tokens are preserved; `regrade_check_ms` reports
the separate grading cost. It must not be interpreted as a newly measured agent
runtime or added to claim a counterfactual end-to-end time.

The audit records original/corrected verdicts, every changed field, source hashes,
checker revision, file snapshots and input/output hashes. Original checker details
remain historical; `regrade_verdict` contains the corrected checker evidence.

Five verdicts change from fail to pass: B4.2 repeats 1 and 3, B5.4 repeats 1 and 3,
and C3 repeat 1. B5.4 repeat 2's reason changes to the strict answer-schema failure;
its verdict remains false. The three remaining failures are:

- B2.1 repeat 1: provider error.
- B5.4 repeat 2: boolean `false` in place of the required integer count `2`.
- C3 repeat 2: client timeout, followed by terminal server cancellation.

The [original-verdict matrix](live-results-original.md) uses the reconciled token
metadata while preserving all original verdicts. The [corrected matrix](live-results.md)
uses the same observations and timing fields. Overall duration statistics have
**n=116**, median **47.374 s** and nearest-rank p95 **107.660 s**. C3's duration
statistics have **n=2**: the timed-out attempt remains in the success-rate
denominator but has no comparable client duration. The server's 210.433-second
measurement is not inserted into that series. Regrading costs are reported
separately and are not added to these historical timings.

## Reproduction without model calls

Use the corrected checker source at `ea39ddc` and a prepared
`project-a-sandbox:cp1` Docker image. The image identities and source hashes are
retained in [the evidence directory](evidence/cp2/README.md). With the original
fixture directories still under `workspaces/`, run from the repository root:

```bash
python3 -m scripts.regrade_observations \
  --input docs/evidence/cp2/live-cp2-reconciled.jsonl \
  --events docs/evidence/cp2/live-cp2-events.json \
  --workspace-root workspaces \
  --output results/reproduced-corrected.jsonl \
  --audit results/reproduced-regrade-audit.json \
  --snapshots results/reproduced-artifacts.json \
  --checker-revision "$(git rev-parse HEAD)"
```

Output paths must be new; the command refuses to overwrite original evidence.
It requires all 117 session event lists, but only the 15 affected artifact
directories. If the original directories are unavailable, restore those 15
directories from `live-cp2-artifacts.json` in an **empty review checkout**, under
`workspaces/<attempt.workspace>`. Each `files` entry with `utf8` is written as
UTF-8 bytes at its relative filename; verify its `sha256` and `bytes` first.
Reject absolute paths, `..`, symlinks and existing destinations. An entry with
`read_error` stays absent; do not invent replacement content. Include every
captured fixture/source file, B5.4's `answer.json` and C3's public test file.
Restoration treats source as data: do not import or execute generated modules on
the host. The regrader itself takes another bounded snapshot before the isolated
Docker evaluator runs hidden tests.

Reproduction should preserve verdicts and the original model metrics; newly
measured grading durations and generated audit/output hashes can differ. The
published audit links the untouched raw campaign through reconciliation to the
specific corrected file that produced the reported matrix. See the
[checkpoint report](cp2-report.md) for the broader validation and limitations.
