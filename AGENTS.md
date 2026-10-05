# Repository Guidelines

## Project Structure & Module Organization

This workspace preserves deployed changes beyond Git HEAD.

- `source/apps/`: Django domain modules, including inventory, assessments, billing, jobs and reports.
- `source/src/agentledger/`: settings and application entrypoints.
- `source/templates/` and `source/static/`: server-rendered UI and assets.
- `source/renderer/`: structured PDF rendering.
- `source/tests/`: pytest qualification.
- `scripts/`: isolated qualification and packaging utilities.
- `docs/`: architecture and release gates.
- `baseline/`: preserved source capture; do not modify.
- `evidence/`: qualification receipts, manifests and logs.

## Build, Test, and Development Commands

From the workspace root:

```powershell
py -3.14 scripts/qualify_local.py
```

Builds the frozen candidate and qualifies it against disposable PostgreSQL containers. Docker Desktop must be running.

From `source/`:

```powershell
uv sync --frozen
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest --cov --cov-report=term-missing
uv run --no-sync python manage.py runserver
```

Direct Django tests require an appropriately configured local PostgreSQL database. Prefer the isolated qualifier for database-authority checks.

## Coding Style & Naming Conventions

Use four-space Python indentation, an 88-character line limit and Ruff formatting. Use `snake_case` for functions and modules, and `PascalCase` for classes. Preserve existing `agentledger` identifiers for compatibility. Add successor migrations instead of editing historical migrations.

## Testing Guidelines

Use pytest and pytest-django; name tests `test_*.py` and functions `test_*`. Configured branch-coverage minimum is 80%. Test tenant isolation, restricted-role SQL, idempotency, expiry, recovery and negative admission paths. Preserve failed evidence; passing reruns do not explain earlier failures.

## Commit & Pull Request Guidelines

Observed history mixes `feat:` prefixes with imperative milestone subjects. Use concise imperative subjects describing the final behavior. PRs should explain the problem, change, validation, authority implications and rollback considerations. Include screenshots for UI changes. Do not commit, push or deploy without session authorization.

## Security & Agent Instructions

Use the name Lyra when communicating with Alexander. Keep secrets out of source, UI, logs and evidence packets. Distinguish observations, declarations, calculations and unknowns. Proposal cards never authorize provider writes.

Preserve deployed worktree changes, strict SSH host-key checking, tenant boundaries and release restrictions. Local tests establish bounded evidence—not production readiness. Production changes require qualified evidence, Lyra’s review and Alexander’s final approval.
