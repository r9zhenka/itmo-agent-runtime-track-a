# B1–B9 and composite benchmark

`baf/cases.py` registers **39 tasks**: the 24 course B1–B8 tasks below, eight
student-original B1.4–B8.4 variants, three B9 constrained-rewriting tasks and four
composites C1–C4. B6–B8 course fixtures live in `baf/code_cases.py`,
`baf/reasoning_cases.py` and `baf/synthesis_cases.py`; the 15 additions are in
`baf/additional_cases.py`, with independent checks in `baf/additional_checks.py`.

| Function | Simple | Medium | Trap |
|---|---|---|---|
| B1 Read/extract | Service port | Payment term in a long contract | Penalty absent from document |
| B2 Search | Find definition | 12 environment reads among 200 files | Same function name, different behavior |
| B3 Create | Typed JSON configuration | Sorted CSV report | Quoted YAML strings `no`, `on`, `0123` |
| B4 Edit | Change only Install version | Rename function/imports/tests | Preserve cp1251 and CRLF |
| B5 Use tools | Run median script | Report 3 failures among 20 tests | `OK` on stdout but exit status 1 |
| B6 Generate code | Unicode slugify | Hourly log aggregation | Record normalization, Unicode, leap-year boundaries |
| B7 Reason | Transfer before boarding closes | Role inheritance and deny precedence | Conflicting rules with context and rule-ID evidence |
| B8 Synthesize sources | Quarterly sales from five CSVs | Accepted decisions from ten meetings | Applicable regulation and differences between two versions |

The course template only includes a complete B1.1 fixture. The other fixtures and
checkers were implemented here from the course catalog's specifications. They are
not claimed to be additional student-original BAF tasks. The separate original
variants, new B9 and composite rationale/contracts are documented in
[the 15 additions](baf-additions.md).

Fixtures are generated deterministically in a fresh workspace per run. The runner
uses the same client/session/message/event/release protocol as the desktop app.
Most checks inspect final files and observed tool events as data. B6 and the
code-generating composites C1/C3 execute candidate functions only inside the
Docker checker described below. B4.2 requires the renamed sources to match the intended minimal edit
and observes `unittest` succeeding inside the command executor. This checker is
deliberately narrow, not a general semantic equivalence test. YAML accepts JSON
(a YAML 1.2 subset) or the simple quoted mapping/list format requested by the task.

## Replay versus model quality

Each task includes a synthetic sequence of tool calls for offline testing. Some
answers are known constants in the script; other commands derive values from the
fixture. This validates dispatch, execution and final-state checking. It is not
a recording of a model and cannot be counted as model-quality evidence.

The live proxy receives the same task prompt, workspace and tool definitions but
does not access the replay sequence. Reports include the actual provider label:
`synthetic-replay` or `live`. Token counts are zero for replay, real provider usage
for live mode. A user-supplied pair label cannot change this provenance.

The checker runs independently after the final event. A successful final event
alone does not make a task pass. Missing or malformed output fails the task.

## Reproduction

With Compose running, `make baf` runs all 39 tasks once. `make baf-smoke` selects
the nine simple tasks B1.1–B9.1. `python3 -m scripts.benchmark --repeats 3` performs three
repeats. Raw JSONL records include task, repeat, verdict, reason, duration, tokens,
provider/model, session/trace IDs, workspace and a quality-evaluation flag.

`make test-ci` runs the same tasks through four local HTTP services with the
test-only fixture executor. This does not establish actual container isolation.
`make check-all` runs the prepared Docker/SSH/FUSE acceptance stack and all 39
replay cases without live LLM calls; see [complete checks and measurements](performance.md).
The final Ubuntu acceptance passed: 169 offline tests, real Docker/grader
checks, 10 hardening checks, all **39/39 replay tasks**, and nine SSH/FUSE checks.
The final Fedora offline suite passed 169 tests. Ten-repeat filesystem and sandbox
measurements also completed; see the [CP2 report](cp2-report.md) and
[raw evidence](evidence/cp2/README.md). These are infrastructure results.

The user-confirmed two-machine acceptance and GUI demonstration are separate from
BAF quality. The first live pair completed all 117 attempts: original verdicts
109/117, corrected verdicts **114/117**, with all affected observations uniformly
regraded and original failures retained. See [results](live-results.md) and
[corrections](evaluation-corrections.md). A separate C3 follow-up passed 3/3;
it does not replace any original attempt. Campaign summaries are produced by
`python3 -m scripts.summarize_benchmark`; keep raw live and replay files separate.

## B6 code generation

No new agent tool is introduced: the agent uses ReadFile, WriteFile and RunCommand.
Each fixture contains `task.md`, a stub `solution.py`, and `test_public.py`. Tasks
must be solved in a single Python source file using only the standard library.
The public examples can be run with `python -m unittest test_public -v`.

| Task | Contract | Hidden inputs |
|---|---|---|
| B6.1 | `slugify(text)` — NFKC, casefold, Unicode alphanumerics, collapsed separators | 9 |
| B6.2 | `aggregate_logs(lines)` — strict UTC timestamps, hourly counts/error counts, ignore invalid lines | 7 |
| B6.3 | `normalize_records(records)` — NFC/casefold names, strict Gregorian dates, deduplication and ordering | 7 |
| B6.4 | `merge_intervals(intervals)` — merge overlapping/touching intervals | 7 |
| C1 | `total_cents(items)` — repair quantity/refund arithmetic | 6 |
| C3 | `parse_duration(text)` — strict duration parser plus integration/tests | 17 |

There are **53 hidden vectors total**, including the original 23 B6.1–B6.3 inputs.
The original B6 fixtures are described below; additional code tasks use their own
file layout and requirements from [the additions](baf-additions.md).

Exact rules and open examples are generated from `baf/code_cases.py`. Replay
solutions live there too, but are not placed in the agent's fixture. Hidden inputs
and literal expected answers live separately in `baf/code_checks.py`. They are
hidden from the benchmark session, not secret from readers of this public repository.
They never enter the agent conversation or the sandbox image.

### Grading boundary

`scripts/benchmark.py` releases the agent session before grading. This stops its
processes before `baf/code_evaluator.py` reads a bounded, non-symlink, regular
candidate source as bytes (`solution.py`, or the declared source file for a
composite). Parent directories are also opened without following symlinks. The
evaluator never imports or compiles the candidate on
the host. It creates a temporary snapshot containing only that file.

For each hidden input it uses the existing SandboxManager to create a fresh Docker
container: network `none`, non-root UID, read-only root and snapshot, capability
drop, CPU/RAM/PID limits, 64 MiB temporary filesystem, bounded logs, and a five-second
deadline including container startup. `/opt/code_worker.py` from the sandbox image
runs with `python -I`, imports the submitted file, and emits the function's return
value as JSON. Only the function name and one input enter that container. Expected
answers and the pass/fail decision remain in the evaluator process outside it.

The checker compares JSON values including numeric types; object key order does
not matter. Missing functions, syntax/import/runtime errors, invalid or oversized
output, incorrect answers, and timeouts fail the task. Every hidden input must
pass. Timeouts and executor/transport errors stop the remaining checks. Cleanup
failure also prevents success. `pass=true` printed by candidate code, changed
public tests, and the agent's own successful final message cannot establish a pass.

The production runner requires a non-root user with Docker socket access on the
same Linux host as its fixture workspaces and snapshot directory. In `--ssh-host`
mode, agent execution runs on the SSH server, but independent grading still runs
with Docker on the client/benchmark host. Build the grading image there too. A
remote Docker daemon for grading is unsupported. No automatic host-execution fallback exists. Offline unit tests
explicitly inject the test-only fixture engine and run **only our known fixtures**;
this is labelled `test-only-fixture` rather than Docker evidence.

Raw benchmark results add `checker_backend`, `checks_passed`, `checks_total`,
`checks_run`, per-input verdicts and `check_ms`. `generation_ms` excludes grading;
`duration_ms` includes both. Actual provider/token metadata still describes the
agent run, not the checker. Incorrect candidates can pass some hidden inputs but
the overall task fails unless all of them pass.

### Commands

```bash
# Rebuild images, then run the normal agent path for a B6 task:
docker compose up --build -d --wait
python3 -m scripts.benchmark --task B6.1 --pair custom+replay

# Check the grader itself with real Docker (no LLM or Compose services needed):
docker build -f sandbox.Dockerfile -t project-a-sandbox:cp1 .
python3 -m scripts.check_b6

# Offline regressions using fixed trusted fixtures:
python3 -m unittest tests.test_code_baf tests.test_baf -v
```

The Docker acceptance test accepts the three reference implementations, rejects
wrong code and forged verdicts, checks read-only mounts/network/secret isolation,
and verifies timeout cleanup. It writes `results/b6-checker.json` and runs in CI.
Passing replay or grader tests is not evidence of an LLM's coding ability; that
still requires a live-model benchmark.

## B7 reasoning

These tasks test decisions derived from supplied facts and explicit rules. Reading
inputs and writing a result are supporting operations. No new agent tool is needed;
the agent may use ReadFile, WriteFile and RunCommand, including code to calculate
an answer. The checker grades the structured result and evidence, not explanatory
prose or private reasoning. Each workspace contains `task.md` and one data file;
the required output is `answer.json`.

| Task | Input and rules | Required evidence |
|---|---|---|
| B7.1 | `journey.json`: arrival + walk versus departure − boarding cutoff; equality permits boarding; dates handle midnight | Boolean decision, ready/closing timestamps, signed integer margin in minutes |
| B7.2 | `policy.yaml`: transitive, multiple inheritance; any matching deny overrides every allow; default deny; exact action/resource | Sorted allowed roles and every role's decision with deduplicated allow/deny rule IDs |
| B7.3 | `rules.json`: opposite effects for the same action/resource applying jointly in a supplied context | Every conflicting pair of rule IDs and all context IDs witnessing it |

The policy fixture uses JSON syntax, a YAML 1.2 subset, and needs no YAML dependency.
B7.2 deliberately includes diamond inheritance, a local allow overridden by an
inherited deny, a role without grants, and irrelevant denies for other operations
or resources. B7.3 uses equal-priority rules with no conflict-resolution policy:
unlike B7.2, deny does not resolve a contradiction. Conditions are conjunctions;
only the supplied contexts count. Same-effect overlaps, different actions/resources,
and conditions that cannot jointly hold in a supplied context are not conflicts.

`baf/reasoning_checks.py` independently calculates the expected JSON from the
original in-memory fixture, never from agent-edited workspace inputs or replay
answers. Output schema and JSON types must match exactly; object field order and
whitespace are irrelevant, while list ordering is specified in each task. Missing
or extra evidence, duplicate JSON keys, non-finite numbers, malformed or oversized
JSON, symlinks, hard links and special output files fail. The checker reads at most
64 KiB and never executes submitted code on the host. These are fixed public
benchmark cases, not secret randomized reasoning tests.

Replay contains manually derived answers and validates the tool/protocol/checker
path only. The independent oracle and negative regressions verify that incorrect
answers fail. Live-model reasoning quality remains to be measured.

```bash
# Offline checker regressions and all-task HTTP integration:
python3 -m unittest tests.test_reasoning_baf tests.test_baf -v

# Rebuild services to load the new cases, then run each through Compose:
docker compose up --build -d --wait
python3 -m scripts.benchmark --task B7.1
python3 -m scripts.benchmark --task B7.2
python3 -m scripts.benchmark --task B7.3
```

The existing CI commands `make test-ci` and `make baf` automatically include B7;
`make baf-smoke` also includes B7.1. No additional workflow step is needed.

## B8 synthesis from sources

Each task requires one consolidated answer supported by multiple local documents.
Reading and writing are supporting operations; the measured result is aggregation,
selection and reconciliation across sources. No new tool or external search is
required: ReadFile, WriteFile and RunCommand are sufficient. All tasks write
`answer.json` using the exact schema in `task.md`.

| Task | Sources | Output and edge cases |
|---|---|---|
| B8.1 | Request and five sales CSVs | Quarter total and per-file totals/counts; exact integer kopecks, inclusive start/exclusive end, signed refunds, zero-contribution files |
| B8.2 | Ten Markdown meeting protocols | Accepted decision IDs, owners, deadlines, file/section citations; proposals and rejections excluded, reaffirmations merged, unassigned fields null |
| B8.3 | Dated request, version catalog and two Markdown regulations | Applicable version, all clause values and only changed clauses, citing both files and clause IDs |

B8.1 uses valid decimal RUB amounts with two fractional digits. Every row is an
independent transaction, including repeated rows; totals use Decimal arithmetic
in the checker and integer kopecks in the answer. Evidence must include all five
files even if one contributes no in-quarter rows.

B8.2 uses narrative minutes with stable decision and section IDs. A decision may
be explicitly reaffirmed in a later meeting; both accepting sections must be cited
in one record. Discussion-only references do not count as reaffirmations. Proposed
dates/owners are not assignments, and an absent assignment is JSON null. There are
six accepted decisions with seven accepting/reaffirming citations in this fixture.
Decision IDs and source sections identify the full text; arbitrary prose summaries
are not graded or required.

B8.3 chooses the approved version with the latest effective date on or before the
request date. In the default fixture, v2 has been approved and published but takes
effect after the request date, so v1 applies. The retention period and response
deadline differ; the region is unchanged and must not be reported as a difference.
Metadata in the catalog agrees with both documents. Publication recency and version
number cannot substitute for the stated effective-date rule.

### Independent grading and provenance

`baf/synthesis_checks.py` computes sales from original in-memory CSV fixtures.
Meeting decisions and regulation clause values use separately curated annotations
outside the workspace; regulation eligibility is calculated from original request
and catalog metadata. The checker never reads replay answers or trusts edited
workspace inputs. Text annotations are fixed fixture-specific ground truth, not
a general natural-language parser; changing the textual fixtures requires reviewing
their annotations. They are visible in this public repository, not secret tests.

B7 and B8 share the bounded data-only JSON reader in `baf/json_output.py`. Output
has a 64 KiB limit; malformed JSON, duplicate keys, non-finite numbers, symlinks,
hard links and special files fail. Fields, JSON types and required list ordering
must match; object key order and whitespace do not matter. A correct grand total
or version alone cannot compensate for missing/incorrect evidence. Generated code
is never imported or executed by these host-side checkers.

Replay reads every source and writes a manually derived answer. All three cases
fit the default 16-step budget. Replay validates dispatch and grading, not model
synthesis quality. Real-model evaluation is still required for quality claims.

```bash
# Offline checker regressions and all-task HTTP integration:
python3 -m unittest tests.test_synthesis_baf tests.test_baf -v

# Load the new cases in Compose, then run the three tasks:
docker compose up --build -d --wait
python3 -m scripts.benchmark --task B8.1
python3 -m scripts.benchmark --task B8.2
python3 -m scripts.benchmark --task B8.3
```

Existing `make test-ci` and `make baf` CI steps automatically include B8.
`make baf-smoke` includes B8.1 and B9.1. The original variants and C1–C4 are
implemented separately; see [additional tasks](baf-additions.md).
