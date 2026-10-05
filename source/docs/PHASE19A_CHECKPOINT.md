# Phase 19A — Stewardence customer entry

Verified 2026-09-04 America/Chicago / 2026-09-05 UTC, Windows Python 3.14.7.

The founder's manual landing page, public signup, three-step organization setup,
and navy/blue visual system are retained. Stewardence replaces the customer-facing
AgentLedger name. The new account is logged in, and setup creates a fresh
organization with OWNER membership and activates it before selecting the real
CSV, manual inventory, or workspace route.

## Verification

- Focused auth/workspace/restricted-role tests: **51 passed** (`scripts/verify_rls.py tests/test_public_signup.py tests/test_workspaces.py tests/test_rls.py -q`).
- Canonical `scripts/test.ps1`: **376 passed**, **88.26% coverage** in 249.91s.
- Additional production collectstatic/WhiteNoise regression: **1 passed**. It builds hashed CSS with production settings and fetches the styled login without a working database. This test was added after the full run began and was verified separately.
- Ruff lint and formatting, migration drift, control-file checks: pass.
- `check --deploy`: exit 0; only the previously accepted HSTS preload warning W021.
- Local browser observation: branded public landing page rendered with the retained design and working signup/login links.
- Original specification SHA-256 remains `E42E9D400D93B269A968322C988A9CDE5B0F244484E81641206CC092DA4AA401`.

## Security correction

The prior runtime database grants did not permit signup or organization insertion.
`organizations.0002_public_onboarding` allows ordinary account registration with
a trigger rejecting privileged account flags for the app role. A fixed-search-path,
owner-executed database function creates only a fresh organization and the current
identity's OWNER membership. Runtime organization/membership INSERT authority
remains absent. The worker cannot provision workspaces. Tests exercise the real
restricted role, reject elevated registration and cross-tenant membership insertion,
and prove another user cannot read the newly provisioned organization.

Django password validators are now configured; signup retains `forms.Form` →
`UserManager.create_user()` → `set_password()`. Honeypot, duplicate identity,
password mismatch, weak passwords, CSRF and hashing checks pass. Duplicate races
are caught at the database uniqueness boundary and return a form error.

Before pushing code that requires the migration, its exact `sqlmigrate` output was
applied to production PostgreSQL in one transaction under `SET LOCAL ROLE
agentledger_owner`, and the Django migration record was written in that transaction.
The transaction committed successfully on 2026-09-05 around 02:14 UTC. This bounded
database session did not inject owner credentials into web or worker.

## Rename evidence

- GitHub repository ID **1356810081** retained; new name `AnarchI-Technologies-MAIN/stewardence-mvp-v1.8`.
- `origin` updated; main still forbids force pushes and deletions and enforces protection for admins.
- Railway project **19870d7e-c1c8-4662-ae99-e53354deb53c** renamed `stewardence-production`.
- Railway workspace **ce83efdb-c6ad-4752-9d98-4bad26eb4667** renamed `stewardence-productions`.
- Web, worker and renderer source repositories verified against the new GitHub name; each has `sleepApplication=false` and the previously successful deployment remains active at verification.
- Existing service IDs, databases, volumes, buckets, hosts, Python imports, roles and cryptographic identifiers preserved. An additional founder-created Postgres service in another environment was observed and left untouched.

## Remaining release gates

Phases 19B–19D are unimplemented gates in the updated checklist. The Collector is
required and no additional Railway container is authorized. Phase 20, live signup
and report-path verification, backup/restore proof, and original Phases 21–23 remain
open. This checkpoint does not claim MVP freeze or complete production acceptance.
