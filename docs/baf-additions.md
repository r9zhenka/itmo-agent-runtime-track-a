# Student tasks and composites

`baf/additional_cases.py` adds 15 deterministic fixtures to the 24 base course
tasks, for **39 tasks** in total. Each task records `origin` and `basis`; these
labels describe intended capabilities, not evidence that a model used a particular
reasoning process. `baf/additional_checks.py` contains independent artifact checks.
The three added code tasks use the isolated evaluator and evaluator-only vectors
in `baf/code_checks.py`. No generated module is imported or executed on the host.

## One student-original task for every course BAF

| Task | Function and fixture | New trap and independent check |
|---|---|---|
| B1.4 | Extract two nested invoice fields | Root-level lookalikes and leading zeros; exact JSON string types |
| B2.4 | Locate invoice plugin registrations | Comments, string examples and plural names are not decorators; AST search over trusted inputs |
| B3.4 | Produce sorted UTF-8 JSONL | Embedded newlines, quotes, Unicode and numeric-looking string IDs; parse each record and require final LF |
| B4.4 | Edit the production INI port | Identical development/comment values; byte-exact preservation of CRLF and other content |
| B5.4 | Interpret a health-probe tool result | Exit 3 means degraded rather than generic failure; stderr suppresses retry; require observed command outcome |
| B6.4 | Implement interval union | Touching endpoints, containment, zero-width intervals and negative coordinates; seven independent hidden inputs |
| B7.4 | Choose a maintenance window | Half-open blackout intervals, minimum length and tie ordering; compute feasibility from original data |
| B8.4 | Consolidate warehouse stock | Reservations reduce availability, recalled SKUs disappear, zero-stock SKUs remain; aggregate original sources with citations |

Each task targets one basis function: extracting known facts, finding the relevant
code, serializing data, making a constrained edit, interpreting a tool, generating
a function, applying rules, or combining sources. Reading and writing necessary
for delivery do not by themselves make these composite tasks. None grades SSH,
sessions, resource limits, mounting, retries or other infrastructure properties.

These fixtures are separately authored student variants rather than relabelling
the course's 24 base tasks. Their output formats and traps are stated in the task
or local specification; hidden checks do not introduce new requirements.

## New B9: following a constrained writing style

The course explicitly gives following a requested style as an example of a new
BAF. Here B9 measures rewriting supplied facts under a style contract. The output
is a small text artifact; there is no subjective language-model judge.

| Task | Difficulty | Style requirement |
|---|---|---|
| B9.1 | Simple | Three ordered labelled lines, specified vocabulary and typography, no greeting or Markdown |
| B9.2 | Medium | Convert an emotional internal incident note to a neutral two-line public update, retaining service/time and omitting private details |
| B9.3 | Trap | Apply the requested lowercase one-line format despite conflicting instructions quoted inside the source document |

The checks are intentionally closed style grammars: lexical choices, fields,
ordering, line endings and exclusions are explicit. This makes the result
reproducible, but it is not a general benchmark of creative writing or stylistic
quality. B3 checks representation of data, while B9's intended variable is adherence
to an externally supplied rewriting/style policy. Their operational overlap is a
limitation of this small basis and should be discussed during the defense.

B9.3 is a model instruction-following test, not an infrastructure security test:
it grades only the written artifact when untrusted text includes an instruction.
The normal sandbox still applies, and no secret is placed in its fixture.

## Composite tasks and decomposition

| Task | Decomposition | Why each step is needed |
|---|---|---|
| C1 (course) | B2 → B1 → B7 → B4 → B5 | Locate the implementation actually imported by the tests; read the issue; infer the quantity/refund error; repair that source; run regressions |
| C2 (course) | B2 → B8 → B7 → B3 | Find the active manifest; combine October spending across its sources; apply strict budget thresholds; produce a complete structured report |
| C3 (course) | B1 → B6 → B5 → B4 | Read the duration specification; implement utility and tests; execute tests/CLI; integrate the CLI and update only the README Usage section |
| C4 (student) | B2 → B8 → B7 → B9 → B3 | Find current incident files; consolidate updates per ID; select open critical incidents; apply public wording/privacy constraints; write the notice |

C1's hidden inputs exercise quantity, zero quantity, refunds and large integer
amounts. Its other fixture files, including regression tests and obsolete code,
must remain byte-identical. C2 excludes out-of-period/archive data and considers
budget equality within budget. C4 must apply latest-status selection before the
severity/status filter, so a previously open but now closed incident disappears.

C3 has 17 evaluator-only duration inputs covering ordering, ranges, invalid types,
ASCII digits, whitespace and large hour counts. Its CLI scaffold is deliberately
specified as three exact Python statements (AST comparison tolerates comments and
formatting), rather than claiming general semantic equivalence. Its three public
unittest assertions are prescribed so their presence can be checked as data. The
agent must also produce observed successful test and CLI results; those logs alone
cannot establish correctness because the utility is independently graded in Docker.

## Grading boundary and reproduction

Output readers reject symlinks, hard links and non-regular files, including symlink
parent directories for nested code artifacts. Reads are bounded to 64 KiB per file.
Malformed JSON, duplicate keys, incorrect types, missing evidence and unexpected
changes fail. Original in-memory fixture data is used for expectations even if an
agent edits its local input files. Some expected text is manually annotated;
changing a fixture requires reviewing those annotations separately from replay.

For B6.4, C1 and C3 the runner releases the agent session before grading and passes
the nominated source file to `FunctionEvaluator`. The evaluator takes only its
bytes into an isolated read-only snapshot as `solution.py`; project imports cannot
bring agent helpers or modified public tests into the hidden grader. C1 and C3
therefore explicitly require the graded implementation to be standalone and use
only the standard library.

```bash
# Offline: trusted fixed fixture execution and negative checker regressions.
python3 -m unittest tests.test_additional_baf tests.test_code_baf -v

# Normal benchmark path, after building and starting the server.
python3 -m scripts.benchmark --task B6.4
python3 -m scripts.benchmark --task C1
python3 -m scripts.benchmark --task C4
```

Synthetic replay proves dispatch and deterministic checking, not model quality.
The production code evaluator requires Docker and does not fall back to running
untrusted code on the host. Tests explicitly inject the fixture executor only for
known reference implementations and deliberate negative mutants. The full
39-task campaign must still report actual provider identity, repeats, failures,
tokens and time; basis/composite success comparisons are evidence to analyze,
not an assumption that the decomposition guarantees success.
