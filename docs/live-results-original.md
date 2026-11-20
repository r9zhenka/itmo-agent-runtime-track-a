# First-pair benchmark — original verdicts

Original 109/117 verdicts are preserved. One timed-out attempt has metadata reconciled from its server trace; this does not change its failed outcome. This matrix uses reconciled metadata (1,396,935 known tokens); the untouched original JSONL reported 1,324,445. See [method and audit](evaluation-corrections.md) and [report](cp2-report.md).

Timings retain original observations (116 recorded durations; the timed-out attempt has no client duration). C3 therefore has only two recorded durations. Regrading cost is separate; known token totals exclude unreported usage.

Status: **complete**. Provenance: **live**.

This contains live-model quality evidence; partial coverage and failures remain visible.

Expected: 39 tasks × 3 repeats per pair. Observed: 117 attempts across 1 pair(s).

Reported tokens: **1396935**. Usage uncertain for **2** attempts; reported totals do not include unreported provider charges.

## BAF × pair

Cells show passed/observed, observed success rate, and coverage observed/expected. Missing attempts are not silently dropped.

| BAF | custom+deepseek-v4.1-flash-1017 |
|---|---|
| B1 | 12/12 (100.0%); coverage 12/12 |
| B2 | 11/12 (91.7%); coverage 12/12 |
| B3 | 12/12 (100.0%); coverage 12/12 |
| B4 | 10/12 (83.3%); coverage 12/12 |
| B5 | 9/12 (75.0%); coverage 12/12 |
| B6 | 12/12 (100.0%); coverage 12/12 |
| B7 | 12/12 (100.0%); coverage 12/12 |
| B8 | 12/12 (100.0%); coverage 12/12 |
| B9 | 9/9 (100.0%); coverage 9/9 |
| C1 | 3/3 (100.0%); coverage 3/3 |
| C2 | 3/3 (100.0%); coverage 3/3 |
| C3 | 1/3 (33.3%); coverage 3/3 |
| C4 | 3/3 (100.0%); coverage 3/3 |

## custom+deepseek-v4.1-flash-1017

Provider: `live`; model: `deepseek-ai/DeepSeek-V4.1-Flash-1017`. Passed 109/117; missing 0/117.

| Group | Pass rate | Repeat rates (coverage) | Spread σ / range | Reported tokens | Unknown usage runs | Duration median / p95, s |
|---|---|---|---|---:|---:|---|
| B1 | 100.0% | #1: 100.0% (4/4); #2: 100.0% (4/4); #3: 100.0% (4/4) | 0.0 / 0.0 pp; n=3 | 135443 | 0 | 29.851 / 85.553 |
| B2 | 91.7% | #1: 75.0% (4/4); #2: 100.0% (4/4); #3: 100.0% (4/4) | 11.8 / 25.0 pp; n=3 | 173107 | 1 | 41.511 / 144.252 |
| B3 | 100.0% | #1: 100.0% (4/4); #2: 100.0% (4/4); #3: 100.0% (4/4) | 0.0 / 0.0 pp; n=3 | 94130 | 0 | 39.121 / 79.538 |
| B4 | 83.3% | #1: 75.0% (4/4); #2: 100.0% (4/4); #3: 75.0% (4/4) | 11.8 / 25.0 pp; n=3 | 167909 | 0 | 76.660 / 101.189 |
| B5 | 75.0% | #1: 75.0% (4/4); #2: 75.0% (4/4); #3: 75.0% (4/4) | 0.0 / 0.0 pp; n=3 | 92813 | 0 | 46.631 / 54.129 |
| B6 | 100.0% | #1: 100.0% (4/4); #2: 100.0% (4/4); #3: 100.0% (4/4) | 0.0 / 0.0 pp; n=3 | 176304 | 0 | 68.100 / 117.169 |
| B7 | 100.0% | #1: 100.0% (4/4); #2: 100.0% (4/4); #3: 100.0% (4/4) | 0.0 / 0.0 pp; n=3 | 91533 | 0 | 40.453 / 58.527 |
| B8 | 100.0% | #1: 100.0% (4/4); #2: 100.0% (4/4); #3: 100.0% (4/4) | 0.0 / 0.0 pp; n=3 | 168978 | 0 | 54.750 / 94.560 |
| B9 | 100.0% | #1: 100.0% (3/3); #2: 100.0% (3/3); #3: 100.0% (3/3) | 0.0 / 0.0 pp; n=3 | 67956 | 0 | 44.850 / 63.679 |
| C1 | 100.0% | #1: 100.0% (1/1); #2: 100.0% (1/1); #3: 100.0% (1/1) | 0.0 / 0.0 pp; n=3 | 36659 | 0 | 64.738 / 78.398 |
| C2 | 100.0% | #1: 100.0% (1/1); #2: 100.0% (1/1); #3: 100.0% (1/1) | 0.0 / 0.0 pp; n=3 | 33728 | 0 | 66.667 / 70.449 |
| C3 | 33.3% | #1: 0.0% (1/1); #2: 0.0% (1/1); #3: 100.0% (1/1) | 47.1 / 100.0 pp; n=3 | 131185 | 1 | 127.516 / 147.372 |
| C4 | 100.0% | #1: 100.0% (1/1); #2: 100.0% (1/1); #3: 100.0% (1/1) | 0.0 / 0.0 pp; n=3 | 27190 | 0 | 42.078 / 44.402 |

### Per-task results

| Task | Passed / observed / expected | Failed | Missing | Reported tokens | Duration median / p95, s |
|---|---|---:|---:|---:|---|
| B1.1 | 3 / 3 / 3 | 0 | 0 | 10969 | 20.650 / 22.209 |
| B1.2 | 3 / 3 / 3 | 0 | 0 | 40778 | 39.878 / 42.935 |
| B1.3 | 3 / 3 / 3 | 0 | 0 | 69662 | 59.861 / 85.553 |
| B1.4 | 3 / 3 / 3 | 0 | 0 | 14034 | 29.432 / 30.269 |
| B2.1 | 2 / 3 / 3 | 1 | 0 | 16909 | 31.802 / 32.378 |
| B2.2 | 3 / 3 / 3 | 0 | 0 | 105499 | 126.339 / 144.252 |
| B2.3 | 3 / 3 / 3 | 0 | 0 | 29579 | 52.290 / 57.624 |
| B2.4 | 3 / 3 / 3 | 0 | 0 | 21120 | 40.146 / 42.475 |
| B3.1 | 3 / 3 / 3 | 0 | 0 | 14845 | 33.342 / 36.873 |
| B3.2 | 3 / 3 / 3 | 0 | 0 | 18701 | 31.389 / 53.408 |
| B3.3 | 3 / 3 / 3 | 0 | 0 | 32995 | 71.893 / 79.538 |
| B3.4 | 3 / 3 / 3 | 0 | 0 | 27589 | 41.368 / 62.834 |
| B4.1 | 3 / 3 / 3 | 0 | 0 | 18247 | 28.231 / 68.082 |
| B4.2 | 1 / 3 / 3 | 2 | 0 | 47041 | 78.487 / 78.927 |
| B4.3 | 3 / 3 / 3 | 0 | 0 | 54163 | 98.020 / 101.189 |
| B4.4 | 3 / 3 / 3 | 0 | 0 | 48458 | 74.833 / 97.852 |
| B5.1 | 3 / 3 / 3 | 0 | 0 | 21070 | 43.271 / 48.252 |
| B5.2 | 3 / 3 / 3 | 0 | 0 | 29972 | 49.469 / 54.129 |
| B5.3 | 3 / 3 / 3 | 0 | 0 | 19089 | 45.245 / 50.498 |
| B5.4 | 0 / 3 / 3 | 3 | 0 | 22682 | 46.642 / 47.508 |
| B6.1 | 3 / 3 / 3 | 0 | 0 | 38167 | 65.669 / 95.308 |
| B6.2 | 3 / 3 / 3 | 0 | 0 | 55310 | 71.998 / 110.708 |
| B6.3 | 3 / 3 / 3 | 0 | 0 | 53609 | 70.530 / 117.169 |
| B6.4 | 3 / 3 / 3 | 0 | 0 | 29218 | 53.942 / 60.348 |
| B7.1 | 3 / 3 / 3 | 0 | 0 | 15340 | 31.596 / 35.128 |
| B7.2 | 3 / 3 / 3 | 0 | 0 | 31131 | 57.440 / 58.527 |
| B7.3 | 3 / 3 / 3 | 0 | 0 | 25465 | 47.132 / 55.797 |
| B7.4 | 3 / 3 / 3 | 0 | 0 | 19597 | 37.678 / 45.463 |
| B8.1 | 3 / 3 / 3 | 0 | 0 | 42971 | 59.831 / 66.355 |
| B8.2 | 3 / 3 / 3 | 0 | 0 | 65593 | 88.695 / 94.560 |
| B8.3 | 3 / 3 / 3 | 0 | 0 | 40661 | 50.044 / 59.632 |
| B8.4 | 3 / 3 / 3 | 0 | 0 | 19753 | 38.801 / 41.517 |
| B9.1 | 3 / 3 / 3 | 0 | 0 | 28834 | 40.683 / 63.679 |
| B9.2 | 3 / 3 / 3 | 0 | 0 | 23060 | 47.092 / 55.602 |
| B9.3 | 3 / 3 / 3 | 0 | 0 | 16062 | 37.875 / 44.850 |
| C1 | 3 / 3 / 3 | 0 | 0 | 36659 | 64.738 / 78.398 |
| C2 | 3 / 3 / 3 | 0 | 0 | 33728 | 66.667 / 70.449 |
| C3 | 1 / 3 / 3 | 2 | 0 | 131185 | 127.516 / 147.372 |
| C4 | 3 / 3 / 3 | 0 | 0 | 27190 | 42.078 / 44.402 |

### Failed attempts

| Task | Repeat | Error kind | Reason |
|---|---:|---|---|
| B2.1 | 1 | model | {"kind": "model", "message": "Provider request failed or returned an invalid completion", "retryable": false} |
| B4.2 | 1 | checker/unclassified | Tests were not observed passing in sandbox |
| B4.2 | 3 | checker/unclassified | Tests were not observed passing in sandbox |
| B5.4 | 1 | checker/unclassified | Probe command result was not observed |
| B5.4 | 2 | checker/unclassified | Probe command result was not observed |
| B5.4 | 3 | checker/unclassified | Probe command result was not observed |
| C3 | 1 | checker/unclassified | CLI result was not observed |
| C3 | 2 | timeout | Timed out waiting for run; reconnect using the last event ID |

p95 uses nearest rank. Repeat-rate spread uses complete repeats only; its sample count is shown. Timing summaries include failed attempts when timings were recorded. Raw JSON and the JSON summary retain missing timings and unknown token usage.
