# Repository Guidelines

## Project Structure & Module Organization

This Python 3.12+ coding-agent runtime uses the standard library. `runtime/` contains four HTTP services (gateway, harness, LLM proxy, sandbox manager), an independent Docker watchdog, Docker integration, and protocol validation. `client/` provides the Tk desktop app and headless CLI. `baf/` defines 39 benchmark tasks: the 24 course B1–B8 tasks, eight original variants, three B9 constrained-rewriting tasks and four composites. Generated-code tasks use independent Docker grading (53 hidden vectors total); other checks inspect data without executing candidate code; `scripts/` contains setup, validation, benchmark, and schema-export commands. Tests and the local fixture executor live in `tests/`. Generated JSON schemas are checked into `contracts/`. Architecture decisions live in `docs/adr/`; generated workspaces and reports go in `workspaces/` and `results/`.

## Build, Test, and Development Commands

Run commands from the repository root:

- `make init`: generate `.env` with random tokens and create the demo workspace; preserve existing configuration.
- `make up`: build and start Docker Compose services, waiting for readiness.
- `make client`: launch the desktop client; requires Tk and a display. Use `python3 -m client --help` for CLI usage.
- `make test-ci`: run all offline tests and update `results/validation.json`.
- `make test-infra` / `make test-ui`: run infrastructure or CLI scenario tests, respectively.
- `make test-docker`: verify real Docker behavior after starting Compose.
- `make baf-smoke` / `make baf`: run nine smoke tasks or all 39 against Compose; generated-code grading requires Docker access on the grading host.
- `make test-b6-docker`: exercise B6 grading and isolation using actual containers, without an LLM.
- `make check-all`: run isolated offline + Docker + replay + SSH/FUSE acceptance after installing the toolchain and building images; use `CHECK_ARGS=--existing-sshd` on an existing development SSH server. It does not call a live LLM.
- `make test-hardening`: exercise real resource limits, export quotas and process-loss cleanup.
- `make measure-sandbox`: measure Docker lifecycle/resource overhead; `python3 -m scripts.measure_mount --help` documents client-to-server filesystem measurements. See `docs/performance.md`.
- `make contracts`: regenerate schemas after protocol changes.
- `make down`: stop Compose and delete its volumes, including traces.

## Coding Style & Naming Conventions

Follow existing Python style: four-space indentation, `snake_case` functions/modules, `PascalCase` classes, and `UPPER_CASE` constants. Keep runtime and offline tests standard-library-only. No formatter or linter is configured. Change schema definitions in `runtime/contracts.py` and `scripts/export_contracts.py`, then regenerate checked-in JSON.

## Testing Guidelines

Use `unittest`, with `tests/test_*.py` modules and `test_*` methods. Run targeted tests with `python3 -m unittest tests.test_protocol -v`. Add regression coverage for changed behavior. No numeric coverage threshold is configured. Offline fixtures do not prove Docker isolation; run Docker checks for sandbox changes. Synthetic replay results do not measure model quality.

## Commit & Pull Request Guidelines

History uses short imperative subjects, sometimes prefixed with a checkpoint or `fix:`; no strict convention is established. Keep commits focused. PRs should explain behavior changes, list validation and limitations, link relevant issues, and include screenshots for visible UI changes. Update protocol documentation or ADRs when architecture changes.

## Security & Configuration

Keep tokens and provider keys in ignored `.env` files. Preserve non-root execution, workspace restrictions, and service isolation: only the manager and independent watchdog receive the Docker socket; only the LLM proxy receives the model key and optional provider Unix socket. Both Docker-socket services are privileged control-plane components. The primary remote export limits content to 256 MiB and entries to 4096. Local RW binds require explicit `ALLOW_LOCAL_RW=1` for trusted development; runtime/Compose default to 0, while `.env.example` opts into 1 for local demos. Never treat local per-file limits as an aggregate quota. See `docs/hardening.md`, `docs/remote-mount.md` and `docs/baf-additions.md`. Transport recovery must not automatically reexecute operations with ambiguous effects.
