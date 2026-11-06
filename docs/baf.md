# B1–B5 benchmark at Checkpoint 1

`baf/cases.py` provides all 15 tasks from the first five course functions:

| Function | Simple | Medium | Trap |
|---|---|---|---|
| B1 Read/extract | Service port | Payment term in a long contract | Penalty absent from document |
| B2 Search | Find definition | 12 environment reads among 200 files | Same function name, different behavior |
| B3 Create | Typed JSON configuration | Sorted CSV report | Quoted YAML strings `no`, `on`, `0123` |
| B4 Edit | Change only Install version | Rename function/imports/tests | Preserve cp1251 and CRLF |
| B5 Use tools | Run median script | Report 3 failures among 20 tests | `OK` on stdout but exit status 1 |

The course template only includes a complete B1.1 fixture. The other fixtures and
checkers were implemented here from the course catalog's specifications. They are
not claimed to be additional student-original BAF tasks. Those, B6–B8 and composite
tasks remain Checkpoint 2 work.

Fixtures are generated deterministically in a fresh workspace per run. The runner
uses the same client/session/message/event/release protocol as the desktop app.
It inspects final files with data-only checkers; it never executes generated code
on the host. B4.2 requires the renamed sources to match the intended minimal edit
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

With Compose running, `make baf` runs all 15 tasks once. `make baf-smoke` selects
the five simple tasks. `python3 -m scripts.benchmark --repeats 3` performs three
repeats. Raw JSONL records include task, repeat, verdict, reason, duration, tokens,
provider/model, session/trace IDs, workspace and a quality-evaluation flag.

`make test-ci` runs the same tasks through four local HTTP services with the
test-only fixture executor. This does not establish actual container isolation.
