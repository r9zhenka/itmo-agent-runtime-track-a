# C3 follow-up after client timeout correction

Three new attempts on code revision `ea39ddc`, using the 900-second client watch
limit and corrected observation checks. All three passed, including 17 independent
hidden vectors each. These results **do not replace** the original C3 attempts or
change the main campaign's 114/117 score. There were no additional follow-up retries.

The run used three concurrent sessions and overlapped the final offline Ubuntu
acceptance, so timings are not a controlled before/after comparison. Its 110,594
reported tokens are separate from the main campaign. All three generation phases
finished before 210 seconds; this follow-up confirms end-to-end operation, but does
not experimentally isolate the old timeout as the sole cause of the earlier failure.
The earlier cancellation is established by its own event/trace evidence.

Reproducibility: [manifest](evidence/cp2/c3-followup-manifest.json),
[raw attempts](evidence/cp2/live-c3-followup.jsonl),
[events](evidence/cp2/live-c3-followup-events.json),
[JSON summary](evidence/cp2/c3-followup-summary.json).

Status: **complete**. Provenance: **live**.

This contains live-model quality evidence; partial coverage and failures remain visible.

Expected: 1 tasks × 3 repeats per pair. Observed: 3 attempts across 1 pair(s).

Reported tokens: **110594**. Usage uncertain for **0** attempts; reported totals do not include unreported provider charges.

## BAF × pair

Cells show passed/observed, observed success rate, and coverage observed/expected. Missing attempts are not silently dropped.

| BAF | custom+deepseek-v4.1-flash-1017-client900-followup |
|---|---|
| C3 | 3/3 (100.0%); coverage 3/3 |

## custom+deepseek-v4.1-flash-1017-client900-followup

Provider: `live`; model: `deepseek-ai/DeepSeek-V4.1-Flash-1017`. Passed 3/3; missing 0/3.

| Group | Pass rate | Repeat rates (coverage) | Spread σ / range | Reported tokens | Unknown usage runs | Duration median / p95, s |
|---|---|---|---|---:|---:|---|
| C3 | 100.0% | #1: 100.0% (1/1); #2: 100.0% (1/1); #3: 100.0% (1/1) | 0.0 / 0.0 pp; n=3 | 110594 | 0 | 198.460 / 211.751 |

### Per-task results

| Task | Passed / observed / expected | Failed | Missing | Reported tokens | Duration median / p95, s |
|---|---|---:|---:|---:|---|
| C3 | 3 / 3 / 3 | 0 | 0 | 110594 | 198.460 / 211.751 |

p95 uses nearest rank. Repeat-rate spread uses complete repeats only; its sample count is shown. Timing summaries include failed attempts when timings were recorded. Raw JSON and the JSON summary retain missing timings and unknown token usage.
