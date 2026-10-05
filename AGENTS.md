# Repository Guidelines

## Project Structure

- `apps/` contains Django domains such as billing, inventory, assessments, jobs, and reports.
- `src/agentledger/` contains project settings and application entrypoints.
- `templates/` and `static/` contain the server-rendered interface and assets.
- `renderer/` contains report rendering code; `collector/` contains the Windows inventory collector.
- `tests/` contains pytest and pytest-django qualification suites; `docs/` records architecture and release evidence.

## Build and Test

Use Python 3.14 and the frozen dependency lock. From the parent development workspace, run `py -3.14 scripts/qualify_local.py` for isolated PostgreSQL qualification. In this repository, run `uv sync --frozen`, `uv run --no-sync ruff check .`, `uv run --no-sync ruff format --check .`, and `uv run --no-sync pytest --cov --cov-report=term-missing`. Direct database tests require configured local PostgreSQL; prefer the isolated qualifier for role and RLS checks.

## Style and Tests

Use four-space Python indentation, Ruff formatting, `snake_case` functions and modules, and `PascalCase` classes. Name test modules `test_*.py` and tests `test_*`. Add successor migrations instead of editing applied migrations. Exercise tenant boundaries, actual database roles, idempotency, expiry, recovery, and denied paths.

## Changes and Security

Use concise imperative commit subjects; `feat:` prefixes appear in existing project history. Pull requests should explain behavior, qualification, authority effects, and rollback. Keep secrets out of source, UI, logs, and evidence. Preserve tenant boundaries, append-only evidence, and customer authorization. Local tests are bounded evidence, not production approval; deployment requires separate release authorization.
