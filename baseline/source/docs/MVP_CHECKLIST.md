# Stewardence Sellable MVP Checklist

**Control baseline:** SPEC-1-AgentLedger-v1.8 plus the owner-approved Railway hosting amendment dated 2026-09-04.
**Specification SHA-256:** `E42E9D400D93B269A968322C988A9CDE5B0F244484E81641206CC092DA4AA401`
**Implementation-handoff SHA-256:** `770AE605E4C71C4C23379748CC64D7D4EEFF9A9CA700756A5118017B2279F17A`

This is the release ledger, not a feature wish list. A checked item means its stated automated tests and required manual verification passed against the named environment. Code existence alone is not proof.

**Founder amendments, 2026-09-04:** Stewardence is the working product name (formerly AgentLedger). Public self-service signup, guided organization setup, and user-initiated deterministic sensing are required for MVP. Phases 19A–19D below supersede the earlier signup/discovery exclusions and must close before Phase 20. Original Phases 21–23 remain required. The supplied specification and its hash, historical evidence, Python package names, database roles, and cryptographic identifiers remain unchanged for compatibility. Name availability is founder-reported research, not a recorded legal clearance.

**Current naming:** GitHub `AnarchI-Technologies-MAIN/stewardence-mvp-v1.8`; Railway project `stewardence-production`, workspace `stewardence-productions`. The existing project, service, database, volume, and bucket identities are retained. The canonical local checkout remains at its existing `agentledger` path.

Status syntax:

- `[ ]` not started
- `[~]` in progress
- `[x]` verified

Evidence for every verified implementation item must name the date, environment, command/test or manual procedure, and durable evidence location. Production-only claims cannot be closed with local evidence.

## Phase 0 — Implementation control files

- [x] The exact supplied `SPEC-1-AgentLedger-v1.8.md` is present and its SHA-256 matches the control baseline. Evidence: exact-copy hash verified locally on 2026-09-04.
- [x] `MVP_CHECKLIST.md` contains the MVP phases, exit conditions, Railway amendment, exclusions, and freeze gate. Evidence: `python scripts/verify_mvp.py --control-files` passed locally on 2026-09-04.
- [x] `DEPLOYMENT_RAILWAY.md`, `SECURITY_INVARIANTS.md`, and `CUSTOMER_PILOT_RUNBOOK.md` are present. Evidence: control-file verification passed locally on 2026-09-04.
- [x] `scripts/verify_mvp.py` validates the control-file set and reports incomplete MVP status without treating file existence as product verification. Evidence: syntax and behavior checks passed locally on 2026-09-04.

## Phase 1 — Repository and Python baseline

- [x] A fresh clone can install the locked dependencies successfully.
- [x] With PostgreSQL available, all migrations run successfully.
- [x] The single selected automated-test strategy runs and passes.
- [x] The Django development server starts.
- [x] Production settings import successfully without weakening production security.
- [x] The server-rendered Django baseline uses minimal vanilla JavaScript and has no Node backend or frontend framework.
- [x] Current official documentation has been checked for Python 3.14, Django 5.2 LTS, PostgreSQL 18, Psycopg 3, Gunicorn, Playwright, `uv`, and Railway; any conflict is documented before an accepted baseline changes.
- [x] The Railway configuration mechanism is explicitly resolved before files are created: current Railway documentation says new services cannot opt into the requested `railway/*.toml` Config-as-Code mechanism.

Phase 1 evidence, 2026-09-04: a Git-metadata-free clean source copy installed 31 locked packages under CPython 3.14.7 and passed Django checks; PostgreSQL 18.6 accepted the two minimal `contenttypes` migrations in the isolated `agentledger-development` container; Ruff and format checks passed; 9 pytest tests passed with 93.42% measured coverage; the live development server returned HTTP 200 from `/healthz` and PostgreSQL/migration-aware `/readyz`; production-settings import and wildcard-host rejection are automated tests. The current Railway Config-as-Code conflict is documented in `DEPLOYMENT_RAILWAY.md` and `railway/README.md`; executable Railway IaC remains correctly deferred to the deployment milestone.

## Phase 2 — Custom user, organization, and tenant control plane

- [x] The custom email-based User model exists before the first permanent migration and uses UUID primary keys where specified.
- [x] Organization and OrganizationMember support owner, admin, assessor, and viewer roles and the enumerated industries.
- [x] User A belongs to Firm A and User B belongs to Firm B in the canonical isolation fixture.
- [x] User A cannot activate Firm B.
- [x] A malformed workspace UUID produces a safe response and never a server error.
- [x] A valid user can switch between two organizations to which that user legitimately belongs.
- [x] Workspace activation is POST-only, CSRF-protected, and revalidates membership before setting organization context.
- [x] User and organization context setters are alias-aware and transaction-local; no persistent session-level tenant setting is used.
- [x] Logout clears the active organization state.

Phase 2 evidence, 2026-09-04, local development against the isolated PostgreSQL 18.6 service: the initial `accounts`, `organizations`, `auth`, and `sessions` migrations applied successfully; `python manage.py makemigrations --check --dry-run` reported no model drift; Ruff format and lint gates passed; and 31 pytest tests passed with 94.19% branch coverage. The automated suite includes case-insensitive email identity and uniqueness, the canonical Firm A/Firm B membership fixture, cross-firm activation denial with session clearing, malformed UUID denial, POST-only and CSRF enforcement, membership revalidation, legitimate two-firm switching, logout state clearing, transaction-local PostgreSQL settings, context-name allowlisting, and explicit database-alias routing.

## Phase 3 — PostgreSQL row-level security (release blocking)

- [x] `agentledger_owner`, `agentledger_app`, and `agentledger_worker` exist with separate credentials and the specified ownership boundary.
- [x] App and worker runtime roles are NOSUPERUSER, NOBYPASSRLS, and do not own tenant business tables.
- [x] Every tenant-owned table has non-null `organization_id`, ENABLE RLS, FORCE RLS, and correct USING and WITH CHECK policies.
- [x] Restricted `app_runtime` and `worker_runtime` aliases prove their actual database identities with `SELECT current_user`.
- [x] Tenant A plus an unfiltered ORM query cannot see Tenant B.
- [x] Tenant A plus raw `SELECT *` cannot see Tenant B.
- [x] Tenant A cannot retrieve Tenant B by a directly supplied primary key.
- [x] An insert carrying Tenant B's organization ID is rejected by PostgreSQL.
- [x] An update aimed at Tenant B affects zero rows or is rejected by PostgreSQL.
- [x] Missing tenant context fails closed.
- [x] Context set on the default connection does not unlock `app_runtime`.
- [x] Worker context cannot access the wrong tenant's business data.
- [x] All tenant-isolation tests pass under the real restricted database roles. Development must stop at this gate if they fail.

Phase 3 evidence, 2026-09-04, local integration against the isolated PostgreSQL 18.6 service: `scripts/verify_rls.py` generated separate high-entropy role credentials in memory, provisioned three LOGIN/NOSUPERUSER/NOBYPASSRLS/NOINHERIT roles without printing those credentials, applied the security migration, and ran the complete suite through distinct `owner_runtime`, `app_runtime`, and `worker_runtime` connections. All 44 tests passed with 93.98% branch coverage, including 13 restricted-role RLS tests. Database introspection proved each alias's `current_user`, `agentledger_owner` ownership of `inventory_items`, forced RLS and non-null organization keys on all current organization-scoped tables, and the tenant policy's USING/WITH CHECK boundary. Canonical A/B rows then proved self-membership bootstrap, unfiltered ORM and raw-SQL isolation, direct-key denial, database rejection of cross-tenant inserts, zero-row cross-tenant updates, missing-context failure, connection-local alias separation, and worker isolation. The development database migration head is `inventory.0002_database_security`; no production state is claimed.

## Phase 4 — Manual inventory

- [x] Inventory supports the specified vendor, owner, department, users, purpose, cost, systems, data, permissions, autonomy, approval, status, and source fields.
- [x] Inventory supports add, edit, archive, search, filter, and detail without Django admin.
- [x] Customer-facing autonomy choices use plain-language behavior descriptions rather than numbered technical levels.
- [x] The required data categories are available.
- [x] A realistic demo bookkeeping company contains at least 10 software/AI inventory items created without Django admin.

Phase 4 evidence, 2026-09-04, local integration against PostgreSQL 18.6: the canonical PowerShell test entrypoint provisioned the restricted roles, recreated the test schema with forced RLS, and passed all 54 tests with 93.83% branch coverage measured across both `apps` and `src`. Inventory tests prove exact cent conversion and display, all required data categories, organization-bound add/detail/edit, immutable discovery source during manual edits, Viewer write denial, direct cross-organization 404 behavior, POST-only archive with removal from the active list, search, status filtering, and a bounded management command that creates exactly ten realistic manual bookkeeping items only in an empty organization and refuses overwrite. Forms render autonomy and access questions as plain business statements; no Django admin route is installed.

## Phase 5 — Small deterministic product catalog

- [x] Roughly 30–50 common AI-enabled products are seeded; the catalog has not expanded into a giant SaaS database.
- [x] Matching uses the accepted exact priority and never uses fuzzy automatic AI classification.
- [x] Known identifiers match deterministically and unknown identifiers remain unknown and require review.
- [x] Mixed-case opaque OAuth identifiers are preserved.
- [x] UUID provider identifiers are canonicalized as UUIDs.
- [x] Unicode hostnames have deterministic IDNA normalization.
- [x] IPv6 addresses with ports normalize correctly.
- [x] Hostname trailing dots normalize correctly.
- [x] `api.example.com` remains distinct from `example.com` unless an explicit alias exists.
- [x] Redirect-URI path and query data are not silently discarded.

Phase 5 evidence, 2026-09-04, local integration against PostgreSQL 18.6: the canonical restricted-role suite passed all 69 tests with 93.75% branch coverage. The idempotent seed creates exactly 40 deterministic product records and 80 aliases; every seeded vendor remains explicitly “Review incomplete,” product-name aliases are exact, hostname aliases remain unusable until verified, and no provider/OAuth identifier is invented. AL-ID-1 regression tests prove mixed-case opaque-token preservation, Microsoft UUID canonicalization, UTS-46/IDNA 3.19 Unicode hostnames, IPv6 plus ports, trailing-dot removal, no subdomain collapse, redirect path/query retention, null-scope collision rejection, priority of immutable provider IDs over exact product names, unknown/unverified outcomes, and conflict-to-review behavior. Restricted-role tests additionally prove global catalog reads and denied catalog writes under `agentledger_app`. Representative official product checks and claim boundaries are recorded in `docs/CATALOG_SEED.md`; no production catalog verification is claimed.

## Phase 6 — Three-step CSV import

- [x] The UI has exactly the three required conceptual steps: select, check/correct, and final approval.
- [x] Parsing and validation write only to tenant-isolated staging, never directly to production inventory.
- [x] Errors use row-specific, nontechnical corrective language.
- [x] Tests cover a valid CSV, invalid row, missing required value, duplicates, cancellation, 100 rows, and cross-tenant staging isolation.
- [x] A 100-row CSV can be uploaded, validated, previewed, corrected, confirmed, and imported transactionally with no partial production writes.

Phase 6 evidence, 2026-09-04, local integration against PostgreSQL 18.6: the canonical PowerShell/restricted-role suite passed all 80 tests with 91.73% branch coverage. The server-rendered workflow labels exactly Step 1 Select, Step 2 Check and correct, and Step 3 Final approval. Tests prove valid staging without inventory writes, row-numbered business-language errors, correction into ready state, missing-column rejection, case-insensitive duplicate detection, POST-only cancellation with complete staging cleanup, Viewer denial, 100-row preview and atomic confirmation, rejection of row 101, and rollback with staging preserved when final inventory persistence is fault-injected. Restricted `agentledger_app` tests prove Firm A cannot read Firm B batches or rows and cannot insert a Firm B batch under Firm A context; both staging tables have non-null organization keys and forced RLS. The database also enforces batch/row organization consistency with a composite foreign key. No production import is claimed.

## Phase 7 — Deterministic policy engine

- [x] The engine is pure Python and performs no database writes, network calls, current-time reads, LLM calls, executable expressions, `eval`, or `exec`.
- [x] Only the accepted operators, results, result fields, and precedence rules are supported.
- [x] Published platform and industry rules are versioned and immutable; a change creates a new version.
- [x] Regression tests prove the same context, rule version, and engine version produce the same output.

Phase 7 evidence, 2026-09-04, local Python 3.14.7: `tests/test_policy_engine.py` passed all 30 focused tests and the canonical PowerShell/restricted-role suite passed all 110 tests with 91.32% branch coverage. `apps/policies/engine.py` imports only Python standard-library definition helpers, accepts only the 12 specified operators and five governance effects over an explicit context-field allowlist, returns the four specified result values with the seven required evidence fields, and evaluates independently ordered layers as Mandatory Platform, Industry, Organization, then Platform Recommendation. An organization PASS remains a separate result and cannot erase a mandatory FAIL. Definitions reject mutable nested values and mutable condition/effect containers. `apps/policies/registry.py` refuses replacement of an existing published name/version while permitting publication under a new version. AST regression checks reject executable built-ins and ambient database, network, clock, or LLM dependencies. Repeated evaluation equality is asserted against engine version `AL-POLICY-1`. Formatting, lint, migration-drift, and Django system checks also passed. This is deterministic local engine evidence; no production evaluation is claimed.

## Phase 8 — Accounting/bookkeeping risk pack

- [x] The only MVP industry pack covers payroll, tax, banking, financial actions, accounting-data modification, client exports, communications/transmission, autonomy, approval, retention, model-training behavior, and vendor-review status.
- [x] Findings use plain business language and never claim AgentLedger blocked or enforced a third-party action.
- [x] A realistic bookkeeping inventory produces findings a nontechnical bookkeeper can understand without technical documentation.

Phase 8 evidence, 2026-09-04, local Python 3.14.7: `apps/policies/packs/accounting.py` publishes the single named MVP industry pack, `accounting_and_bookkeeping` version `1.1.0`, with 11 immutable rules covering the required accounting subjects. The pack uses "vendor review is incomplete" and describes approval, review, documentation, and source-system operating procedures without claiming AgentLedger blocked, stopped, intercepted, prevented, or enforced an action. `tests/test_accounting_policy_pack.py` evaluates realistic payroll/tax and autonomous banking/accounting inventory contexts and asserts understandable explanations and corrective actions for a bookkeeper, subject coverage, exact rule IDs and version, enforcement-claim exclusions, and repeatability. All 38 focused policy tests and the canonical PowerShell/restricted-role suite passed; the full suite passed all 118 tests with 91.39% branch coverage. Formatting, lint, migration-drift, and Django system checks also passed. This is local deterministic policy-pack evidence; customer comprehension and production behavior are not claimed beyond the tested language and contexts.

## Phase 9 — Deterministic risk engine

- [x] The eight dimensions, weights, 0–100 scales, weighted sum, and Low/Moderate/High/Critical bands match the approved baseline.
- [x] Mandatory-rule severity/risk floors apply deterministically.
- [x] Every contribution stores reason, rule, dimension, and points.
- [x] Every score visible in the UI answers “Why did this receive this score?” without source-code inspection.

Phase 9 evidence, 2026-09-04, local Python 3.14.7 and Django test client against PostgreSQL 18.6: `apps/policies/risk.py` defines exactly Data Sensitivity 20%, System Privilege 20%, Autonomy 15%, External Connectivity 15%, Human Oversight 10%, Financial Impact 10%, Regulatory Relevance 5%, and Vendor Risk 5%. Each dimension is clamped to 0–100; the Decimal weighted sum uses deterministic half-up integer rounding; the exact 0–24 Low, 25–49 Moderate, 50–74 High, and 75–100 Critical boundaries are tested. Risk contributions retain reason, rule ID/version, dimension, and signed integer points. Severity-floor effects raise both the score to the corresponding band minimum and the band, including a repeated-evaluation proof for a mandatory-platform Critical rule. The inventory detail evaluates the versioned accounting pack over a complete normalized context and visibly presents score/band, the question "Why did this receive this score?", signed rule/version explanations, all eight dimension calculations, the pre-floor weighted total, matched findings, and next steps. Missing retention/training evidence remains explicitly unknown. All 70 focused tests and the canonical PowerShell/restricted-role suite passed; the full suite passed all 140 tests with 91.27% branch coverage. Formatting, lint, migration-drift, and Django system checks also passed. This is local deterministic/UI response evidence; no production assessment is claimed.

## Phase 10 — ROI engine

- [x] Inputs, assumption provenance, and formulas match the approved baseline.
- [x] The UI displays the arithmetic used for every result.
- [x] Zero-cost denominators never produce infinity or divide-by-zero failures.
- [x] A customer can reproduce every displayed ROI number with a calculator.

Phase 10 evidence, 2026-09-04, local Python 3.14.7 and Django test client against PostgreSQL 18.6: `apps/roi/engine.py` calculates monthly labor value, monthly value, amortized implementation cost, total monthly cost, monthly net value, and ROI using Decimal arithmetic and version `AL-ROI-1`. Subscription cost, implementation cost, its explicit amortization period, hours saved, loaded hourly rate, additional attributable revenue, and avoided monthly cost each retain one of the exact Measured, Customer supplied, Estimated, or Unknown labels; unknown nonzero inputs fail closed. The tenant-scoped inventory ROI page displays every formula with substituted values, every assumption source, and the half-up nearest-cent rounding rule. A zero monthly total cost returns an explicit unavailable result without division or infinity. Exact example arithmetic, three-month rounding, repeated evaluation, invalid inputs, ambient-dependency exclusion, tenant isolation, form correction, and rendered output are tested. The canonical PowerShell/restricted-role suite passed all 153 tests with 91.68% branch coverage. Formatting, lint, migration-drift, and Django system checks also passed. This is local deterministic/UI response evidence; no customer-entered production ROI record is claimed.

## Phase 11 — Immutable assessment snapshots

- [x] A snapshot captures inventory, evidence references, platform/industry and organization rule versions, risk configuration, ROI assumptions, timestamp, and engine version.
- [x] Canonical input and result SHA-256 hashes are stored with assessment identity and version metadata.
- [x] Inventory, rules, or ROI edits cannot mutate historical assessments.
- [x] Yesterday's assessment remains identical after today's changes.

Phase 11 evidence, 2026-09-04, local Python 3.14.7 and PostgreSQL 18.6: `apps/assessments/snapshots.py` requires an explicit timezone-aware capture time and records a canonical whole-tenant inventory copy, evidence references, explicit absent platform-pack state, accounting industry-pack version, organization rule versions, all eight risk weights/version, every ROI value/provenance, policy/risk/ROI engine versions, and complete policy/risk/ROI results. RFC 8785 canonical input and result bytes are independently SHA-256 hashed and stored with a UUID assessment identity, snapshot schema version, and monotonically extended revision. Payloads are normalized through canonical bytes before insertion so immediate and database-round-trip representations are identical. The model rejects mismatched hashes, instance updates, and deletes; a PostgreSQL trigger rejects bulk UPDATE/DELETE, while grants and forced RLS limit app/worker roles to tenant-scoped SELECT/INSERT. Prior hashes are verified and only the latest stored revision may be extended. A regression creates yesterday's snapshot, edits inventory, rule-version references, and ROI assumptions today, then proves the prior payloads and hashes remain byte-canonically identical while a new version records the changes. The tenant-scoped UI can save and open a hash-verified snapshot; Viewers cannot save one. The canonical PowerShell/restricted-role suite passed all 162 tests with 91.96% branch coverage, including 16 restricted-role tests. Formatting, lint, migration-drift, migrations, and Django system checks passed. This is local persistence and isolation evidence; no production snapshot is claimed.

## Phase 12 — Visual no-code rule builder

- [x] Sentence-style controls can create, edit, duplicate, disable, delete, test, and explain rules.
- [x] Only the approved non-enforcement effects are available; blocking, revocation, permission changes, and other enforcement effects are unavailable.
- [x] Structured JSON is hidden behind “View technical details” and contains no executable code.
- [x] State-changing operations are POST-only and CSRF-protected.
- [x] A nontechnical user can create the payroll plus external-transmission human-approval/High-floor example without code.

Phase 12 evidence, 2026-09-04, local Django test client against PostgreSQL 18.6: the organization-rule UI presents sentence fields for "This software accesses," "This software can," "Minimum risk level," and "Require this control." It supports create, edit with version increment, collision-safe duplicate, enable/disable with version increment, delete, unsaved test against tenant inventory, and plain-language explanation. The exact payroll plus external-transfer, human-approval, High-floor example is created without entering code. The builder exposes only risk points, severity floor, required control, finding creation, and review recommendation; organization-authored points cannot be negative and PASS is unavailable, so the firm can add stricter findings without reducing baseline risk. The compiler accepts only `all`/`effects`, allowlisted condition fields/operators, and approved effects; enforcement and executable-shaped definitions fail closed. JSON is auto-escaped and shown only under "View technical details." All writes are POST paths with CSRF tokens, and enforced-CSRF tests reject tokenless create, edit, duplicate, toggle, and delete. Forced RLS isolates organization rules for app and worker roles; the worker is read-only and cross-tenant inserts fail. Enabled rule definitions and versions are canonically copied into later snapshots, while prior snapshots retain their historical copies. All 12 focused builder tests passed; the canonical PowerShell/restricted-role suite passed all 175 tests with 91.98% branch coverage, including 17 restricted-role tests. Formatting, lint, migration-drift, migrations, and Django system checks passed. This is local workflow evidence; no customer usability session or production rule is claimed.

## Phase 13 — PostgreSQL background jobs

- [x] Durable jobs use PostgreSQL LISTEN/NOTIFY, SKIP LOCKED, claim tokens, leases, fencing, retry schedule, and recovery scans; Redis and Celery are absent.
- [x] Only the approved MVP job types are present; Microsoft and Google discovery jobs are absent.
- [x] Retry timing uses the locked database row, never caller-provided attempts.
- [x] Two workers racing for one job yield one winner.
- [x] An expired lease can be reclaimed by a second worker.
- [x] Stale-worker completion and failure are rejected.
- [x] A missed notification is recovered by periodic scanning.
- [x] A job created before LISTEN is found by the initial scan.
- [x] Jobs remain correct across concurrency, worker crash, connection restart, and missed notification.

### Phase 13 Verification — VERIFIED 2026-09-04

Environment:

- Windows local development environment
- Python 3.14.7
- Django 5.2.17
- PostgreSQL 18.6
- restricted runtime roles exercised through `scripts/verify_rls.py`

Verified implementation:

- PostgreSQL is the durable job queue.
- `LISTEN/NOTIFY` is a wake-up optimization rather than authoritative queue state.
- Queue claiming uses `FOR UPDATE SKIP LOCKED`.
- Claims use unique fencing tokens.
- Running jobs use bounded leases and heartbeat renewal.
- Expired leases are recoverable by another worker.
- Stale workers cannot complete or fail a reclaimed job.
- Retry timing is derived from the persisted database attempt count.
- Fifth failure becomes terminal.
- Initial scan recovers jobs created before LISTEN registration.
- Periodic scans recover missed notifications and delayed work.
- Listener reconnect behavior is verified.
- Live PostgreSQL notification delivery is verified.
- Runtime drains available jobs until empty.
- Business preparation and persistence execute under tenant context.
- External work executes outside the tenant database transaction.
- Durable failure records contain safe summaries/fingerprints rather than exception secrets.

Approved MVP job types only:

- `risk_reassessment`
- `report_generation`
- `catalog_refresh`
- `audit_batch_seal`

Explicitly absent from the MVP queue:

- Microsoft discovery jobs
- Google discovery jobs
- Redis
- Celery

Database security boundary verified:

- `agentledger_app` queue visibility is tenant-scoped.
- `agentledger_app` cannot insert jobs for another tenant.
- `agentledger_app` cannot mutate queue execution state.
- `agentledger_worker` may discover and claim queue work across tenants.
- Global worker queue visibility does not grant cross-tenant access to business tables.
- `background_jobs` uses forced PostgreSQL RLS.
- queue table ownership remains `agentledger_owner`.

Evidence:

- focused Phase 13 queue/runtime and JSON hydration suite: 17 passed
- restricted-role RLS suite: 22 passed
- canonical repository suite: 196 passed
- canonical coverage: 92.36%
- Django system check: no issues
- migrations: current, no unapplied Phase 13 migration

Phase 13 status:

**VERIFIED**

Next authorized phase:

**Phase 14 — Audit Events and Deterministic Merkle Sealing**

## Phase 14 — Audit events and Merkle sealing

- [x] All enumerated business and security-relevant events are recorded independently of later sealing.
- [x] Complete event envelopes use RFC 8785 canonicalization, domain-separated SHA-256, AL-MERKLE-1, tenant chain heads, block metadata, and a verification command.
- [x] Only the tenant's chain-head row is locked while sealing; different tenants can seal concurrently.
- [x] Modifying, deleting, or reordering a sealed event makes verification fail.
- [x] Concurrent same-tenant sealers produce one chain advancement.
- [x] Different tenants can seal concurrently.
- [x] UI claims only tamper evidence/valid verification, never magical immutability, blockchain protection, or unhackability.

Phase 14 verification date:

**2026-09-04**

Environment:

- Windows local development environment
- Python 3.14.7
- Django 5.2.17
- PostgreSQL 18.6
- restricted application and worker roles provisioned through `scripts/verify_rls.py`

Verified implementation:

- `append_audit_event()` validates the exact event registry, UUIDs, string JSON keys, object-root payloads, binary-float exclusion, and complete RFC 8785-compatible event envelopes.
- Audit insertion and `audit_batch_seal` enqueue occur in one tenant transaction without synchronous chain-head mutation.
- Existing manual inventory create/edit/archive, CSV inventory import and final reconciliation acceptance, organization-rule create/edit/duplicate/toggle/delete, and assessment completion actions emit their applicable exact audit events atomically with business state.
- At Phase 14 closure, excluded discovery, connector, and report behavior remained unwired; its event vocabulary was reserved only. Phase 15 subsequently wired report generation.
- `AL-MERKLE-1` uses RFC 8785, domain-separated SHA-256 leaf/node/block hashes, deterministic largest-power-of-two splitting, and `AL-BLOCK-1` envelopes.
- Sealing orders events by `occurred_at ASC, id ASC`, locks only the tenant chain head, caps blocks at 1,000 events, writes seal metadata once, and advances the tenant-local block-hash chain atomically.
- Audit persistence requests PostgreSQL `REPEATABLE READ` before tenant activation. A synchronized two-transaction specimen proves an event committed after Transaction A's snapshot remains unsealed until block N+1.
- Same-tenant concurrent sealers advance the chain once; different tenants seal successfully in parallel.
- Forced RLS and restricted grants protect audit events, blocks, and chain heads. Runtime roles cannot alter committed event fields, rewrite sealed metadata, or update/delete Merkle blocks.
- `verify_audit` and `verify_tenant_audit_history()` return only `VALID`, `INVALID`, or `INCOMPLETE` and recalculate complete event envelopes, leaf hashes, Merkle roots, block envelopes/hashes, links, sequence continuity, membership/order, and the chain head.
- Privileged test-only tampering proves modification and reordering return `INVALID`; deletion returns `INCOMPLETE`. Production triggers remain enabled and unchanged after each specimen.
- No audit UI makes an immutability, blockchain, unmodifiable, impossible-to-alter, or unhackability claim. The verification command accurately describes local history as tamper-evident.

Evidence:

- focused Phase 14 regression across audit, jobs, RLS, inventory, CSV, rules, and snapshots: 149 passed
- snapshot and concurrent-sealing specimens: 3 passed
- verifier status, command, and tamper specimens: 6 passed
- dedicated restricted-role audit RLS suite: 10 passed
- canonical repository suite through `scripts/test.ps1`: 286 passed
- canonical branch coverage: 91.80%
- Ruff format and lint checks: passed
- Django system check: no issues
- migration drift: none
- durable repository evidence: `apps/audit/`, `apps/jobs/`, `src/agentledger/tenancy/context.py`, applicable business-action views/services, and Phase 14 tests under `tests/`

Phase 14 status:

**VERIFIED**

Next authorized phase:

**Phase 15 — Canonical Browser Reporting**

## Phase 15 — Canonical browser reporting

- [x] One canonical report context drives browser and PDF reports.
- [x] The report contains every required section and version/identity field.
- [x] Report identifiers use the accepted deterministic sequence.
- [x] The report is titled as an AI Risk & ROI Assessment and makes no unsupported compliance or security guarantee.

Phase 15 verification date:

**2026-09-04**

Environment:

- Windows local development environment
- Python 3.14.7
- Django 5.2.17
- PostgreSQL 18.6
- restricted application and worker roles provisioned through `scripts/verify_rls.py`

Verified implementation:

- `build_report_context()` is the single immutable-snapshot-derived payload for the browser template and the Phase 16 PDF renderer boundary.
- The canonical context includes report and organization identity, assessment date, ruleset versions, executive summary, inventory, risk overview, individual risk findings, failed/warning policy findings, recommendations, AI expenditure, ROI, methodology, and evidence.
- Reports capture organization display identity and reference the immutable assessment snapshot; later live inventory or organization-name changes do not alter report content.
- PostgreSQL allocates globally unique, monotonic identifiers in the accepted `AL-YYYY-NNNNNN` form. Generation is idempotent per assessment snapshot under a transaction-scoped advisory lock.
- Report creation and the exact `report.generated` audit event commit atomically. Database constraints and triggers reject cross-tenant snapshots and report mutation or deletion.
- Forced RLS and restricted grants allow tenant-scoped application creation/read and worker read only; viewers cannot generate reports and cross-tenant report access returns not found.
- The browser report title is exactly `AI Risk & ROI Assessment`, automatically escapes snapshot content, and states that the report is decision support rather than a compliance certification or security guarantee.

Evidence:

- focused report, assessment, audit, and RLS regression: 62 passed
- canonical repository suite through `scripts/test.ps1`: 297 passed
- canonical branch coverage: 91.42%
- Ruff format and lint checks: passed
- Django system check: no issues
- migration drift: none
- durable repository evidence: `apps/reports/`, `templates/reports/detail.html`, report integration in the assessment detail view, report migrations, and `tests/test_reports.py` plus report RLS specimens in `tests/test_rls.py`

Phase 15 status:

**VERIFIED**

Next authorized phase:

**Phase 16 — Isolated PDF Renderer**

## Phase 16 — Isolated PDF renderer

- [x] A separate renderer has no public domain and receives no database, OAuth, KEK, or unnecessary bucket credentials.
- [x] The renderer accepts validated structured data and fixed templates, never customer-provided arbitrary HTML or output paths.
- [x] Chromium runs non-root inside the hardened renderer-container isolation boundary; JavaScript is off, service workers are blocked, and every browser request is aborted.
- [x] Customer strings are escaped and payload, time, output size, process, CPU, memory, PID, filesystem, and temporary-output limits are enforced where supported.
- [x] Script, remote image/CSS, `file://`, traversal, and network-fetch payloads cannot execute, fetch, or read sensitive local files.

Phase 16 verification date:

**2026-09-04**

Environment:

- Windows local development environment
- Python 3.14.7
- Django 5.2.17
- PostgreSQL 18.6
- Docker Desktop / Docker Compose local renderer environment
- Playwright Chromium installed inside the dedicated renderer image
- restricted application and worker roles provisioned through `scripts/verify_rls.py`

Verified implementation:

- The PDF renderer is a separate service with no published ports and no public domain.
- The renderer receives no PostgreSQL credentials, OAuth credentials, key-encryption keys, or bucket credentials.
- The renderer accepts only a strict structured Phase 15 report payload and fixed template code; customer-provided arbitrary HTML, filesystem paths, output paths, scripts, URLs, remote CSS, remote images, and traversal-shaped fields are rejected.
- Payload validation enforces the accepted report schema, a 1 MiB request ceiling, bounded strings, bounded collections, bounded nesting, UUID and report-ID formats, exact SHA-256 encoding, strict JSON serialization, and forbidden active/path/network field names.
- Customer strings are escaped before HTML rendering.
- JavaScript is disabled, service workers are blocked, and every browser request is aborted.
- PDF generation executes under a hard process timeout and uses only the controlled `/work/output` temporary filesystem.
- Rendered output is removed after response completion; the live specimen left `remaining_output_files=[]`.
- The renderer executes as UID/GID `10001:10001` with a read-only root filesystem.
- Linux capabilities are dropped with `CapDrop=["ALL"]`.
- `no-new-privileges` is active.
- The renderer uses the official Playwright default-deny seccomp profile with `SCMP_ACT_ERRNO`.
- Runtime limits are enforced at 256 PIDs, 768 MiB memory, and 1 CPU.
- No host ports are published.
- The renderer network is internal-only. Live specimens proved PostgreSQL name/access unavailable and external network access unavailable.
- Invalid renderer input returns HTTP 422 without leaking tracebacks or Playwright implementation details.
- A live canonical `/v1/render` request returned HTTP 200, `application/pdf`, `Cache-Control: no-store`, valid `%PDF-` bytes, and left no temporary output artifacts.
- Chromium's internal browser sandbox is intentionally disabled for the MVP because the bundled Chromium build reproducibly aborted during Linux zygote sandbox startup when `chromium_sandbox=True`.
- The hardened non-root container/process boundary is therefore the explicit MVP renderer isolation authority.
- Disabling Chromium's internal sandbox does not weaken the documented outer controls: non-root execution, read-only root filesystem, dropped capabilities, no-new-privileges, default-deny seccomp, internal-only networking, browser-request abortion, bounded resources, controlled temporary storage, hard timeout, strict structured input, and output cleanup remain enforced.
- No claim is made that Chromium itself is sandboxed.

Evidence:

- focused renderer regression after final formatting: 16 passed
- canonical repository suite through `scripts/test.ps1`: 313 passed
- canonical coverage: 90.15%
- live canonical render: HTTP 200 / `application/pdf` / valid `%PDF-`
- invalid-payload specimen: HTTP 422 with no traceback or Playwright-detail leakage
- renderer PostgreSQL access: blocked
- renderer external network access: blocked
- renderer output cleanup: verified empty after successful rendering
- effective container boundary: non-root UID/GID 10001, read-only root, all capabilities dropped, no-new-privileges, default-deny seccomp, 256 PID limit, 768 MiB RAM limit, 1 CPU, no published ports
- Ruff format: 160 files already formatted
- Ruff lint: all checks passed
- `git diff --check`: clean
- Django system check: no issues
- migration drift: none
- Docker Compose validation: valid
- durable repository evidence: `Dockerfile.renderer`, `compose.yaml`, `deploy/playwright-seccomp.json`, `renderer/`, `tests/test_renderer.py`, and Phase 15 canonical report-context integration

Phase 16 status:

**VERIFIED**

Next authorized phase:

**Phase 17 — Private Report Storage**

## Phase 17 — Private report storage

- [x] PDFs and future exports/certificates are stored in the private `reports` object bucket, never ephemeral application storage.
- [x] PostgreSQL records object key, content type, SHA-256, size, report ID, creation time, and assessment snapshot ID.
- [x] Object keys use organization/assessment/report scoping and are never sufficient authorization.
- [x] Authenticated membership, tenant RLS, and report ownership are checked before a short-lived presigned GET or authenticated proxy response.
- [x] Tenant A cannot retrieve Tenant B's report even with Tenant B's report UUID and object key.
- [x] Before customer data, the absence of bucket API server-side-encryption controls, versioning, object locks, and lifecycle rules in current Railway documentation has a documented, owner-approved security disposition.

**Phase 17 verification — VERIFIED 2026-09-04**

- Canonical repository suite: 334/334 passed.
- Canonical coverage: 88.60%, above the required 80% threshold.
- Report artifact RLS regression: 26/26 passed under the restricted-role harness.
- Restricted worker regression: 11/11 passed under the restricted-role harness.
- Phase 17 focused storage/report-generation suite: 27/27 passed.
- Final report-generation enqueue seam regression: 10/10 passed.
- The authenticated Generate action now schedules `REPORT_GENERATION` with the exact payload `{"report_id": "<uuid>"}`.
- Report-generation scheduling is report-scoped and idempotent for queued/running work: repeated Generate requests reuse the active job rather than creating duplicate PDF jobs.
- If an immutable report artifact already exists, no additional generation job is scheduled.
- A terminal failed generation job does not permanently poison the report; a later authorized Generate action may enqueue a fresh attempt.
- Production-settings regression: 1/1 passed after updating the explicit production configuration fixture for the required private-report storage and renderer variables.
- Django system check: clean.
- Migration drift: none.
- Ruff format: clean.
- Ruff lint: clean.
- `git diff --check`: clean.
- Production report storage is fail-closed when required bucket or renderer configuration is absent.
- Report artifacts use deterministic organization/assessment/report-scoped keys, persisted SHA-256 and byte-size metadata, authenticated delivery, tenant RLS, and ownership checks.
- Renderer execution receives no report-bucket credentials.
- Live Railway bucket creation, credentials, and production connectivity remain a Phase 20 deployment proof and are not claimed by this local Phase 17 verification.
- Owner security disposition approved 2026-09-04 for the founder-assisted MVP regarding Railway bucket API/documentation limitations around application-configurable server-side-encryption controls, versioning, object locks, and lifecycle rules. This acceptance does not claim Railway lacks encryption at rest or that report objects are immutable. The disposition must be revisited before broader production use if customer, contractual, regulatory, or compliance requirements require those controls.
- Fresh official Railway Storage Buckets documentation verification on 2026-09-04 explicitly lists server-side encryption, object versioning, object locks, and bucket lifecycle configuration as not yet supported.
- The same current Railway documentation confirms buckets are private and supports authorized delivery through presigned URLs or backend proxy responses.
## Phase 18 — Credential cryptography module

- [x] The connector-ready module implements versioned KEKs, per-record DEKs, AES-256-GCM, tenant/record AAD binding, normal rotation, and compromised-key rotation without creating production OAuth credentials.
- [x] Wrong tenant AAD, record AAD, or key causes decryption failure.
- [x] Normal rotation keeps existing ciphertext recoverable.
- [x] Compromised-key rotation creates a new DEK and ciphertext.
- [x] Old KEKs cannot be removed while an active envelope references them.

### Phase 18 verification evidence

- cryptography==50.0.1 supplies the AES-GCM primitive; no custom cipher construction is introduced.
- CredentialEnvelope records the envelope version, KEK version, wrapped-DEK nonce and ciphertext, payload nonce, and credential ciphertext.
- Each credential receives a newly generated 256-bit DEK.
- KEKs are exactly 256 bits and are addressed by positive integer version.
- Both DEK wrapping and credential encryption authenticate tenant UUID and record UUID through domain-separated AAD.
- Wrong tenant AAD, wrong record AAD, and an incorrect KEK with the same version number all fail authenticated decryption.
- Normal KEK rotation unwraps and rewraps the existing DEK under the active KEK. Credential ciphertext and payload nonce remain unchanged and both the pre-rotation and rotated envelopes remain decryptable while their referenced KEKs remain available.
- Compromised-key rotation decrypts the credential and creates a fresh DEK, fresh nonces, fresh wrapped DEK, and fresh credential ciphertext under the active KEK.
- VersionedKEKRing.remove_kek() rejects removal of the active KEK and rejects removal of an older KEK while any supplied active envelope still references it.
- KEK lifecycle enforcement is intentionally module-level in the connector-ready MVP. A future persistence layer must supply the authoritative active-envelope set before key removal.
- No connector model, OAuth client credential, access token, refresh token, or production connector secret is created by Phase 18.
- Focused Phase 18 cryptography suite: 10/10 passed.
- Canonical repository suite: 344/344 passed.
- Canonical coverage: 88.24%, above the required 80% threshold.
- Migration drift: none.
- Repository Ruff format and lint checks: clean.
- git diff --check: clean.
- **Phase 18 status: VERIFIED.**
## Phase 19 — Security and production settings

- [x] Production uses DEBUG=False, secure cookies, CSRF, HTTPS awareness, appropriate HSTS, explicit hosts/origins, strong secrets, clickjacking/content-type defenses, and secret-safe request logging.
- [x] ALLOWED_HOSTS = ["*"] is absent; actual Railway/custom hosts and Railway's healthcheck hostname are handled explicitly.
- [x] /healthz proves process liveness without tenant context.
- [x] /readyz proves application readiness, database connectivity, and required migration state without tenant context.
- [x] Production security validation and Django deployment checks pass.

### Phase 19 verification evidence

- Production settings force DEBUG=False.
- Production refuses a missing, short, low-diversity, or django-insecure- prefixed DJANGO_SECRET_KEY.
- Production requires explicit ALLOWED_HOSTS, rejects wildcard hosts, and explicitly includes Railway's healthcheck.railway.app healthcheck hostname.
- Production requires explicit HTTPS CSRF_TRUSTED_ORIGINS and rejects wildcard or insecure HTTP origins.
- SECURE_PROXY_SSL_HEADER recognizes the trusted HTTPS proxy signal and SECURE_SSL_REDIRECT=True enforces HTTPS-aware application behavior.
- Session and CSRF cookies are secure; session cookies are HTTP-only; both use SameSite=Lax.
- HSTS is enabled at 3600 seconds with subdomains included. HSTS preload remains intentionally disabled during the initial production ramp-up and must not be represented as enabled.
- SECURE_CONTENT_TYPE_NOSNIFF=True and X_FRAME_OPTIONS="DENY" provide content-type and clickjacking defenses.
- Gunicorn access logs record method and URL path without query strings, request headers, cookies, referrers, or request bodies.
- /healthz bypasses tenant resolution and returns process liveness without requiring authentication, tenant context, database access, or migration inspection.
- /readyz bypasses tenant resolution, verifies database connectivity with SELECT 1, verifies that Django has no pending migration plan, and returns 503 {"status":"not_ready"} when readiness fails.
- Stale or invalid authenticated tenant session state cannot prevent /healthz or /readyz from reaching their health logic.
- Focused Phase 19 security/baseline suite: 22/22 passed.
- Canonical repository suite: 357/357 passed.
- Canonical coverage: 88.25%, above the required 80% threshold.
- Migration drift: none.
- Repository Ruff formatting and lint checks: clean.
- git diff --check: clean.
- Django check --deploy exited successfully. Its only security warning was security.W021, expected because HSTS preload is intentionally deferred during the initial 3600-second ramp-up.
- No Railway deployment, production variable mutation, custom-domain change, production database mutation, or production bucket operation occurred in Phase 19.
- **Phase 19 status: VERIFIED.**
## Phase 19A — public customer entry and guided setup

Required gates:

- [x] Public anonymous landing page exposes real Stewardence value and a working signup path.

- [x] Public self-service signup creates a valid account without invite-only dependency.

- [x] Passwords flow through Django's secure password hashing path and are never stored in readable form.

- [x] Case-insensitive duplicate account identity is rejected safely.

- [x] Signup abuse honeypot remains functional without being confused with organization metadata.

- [x] Successful signup logs the user in and enters guided organization setup.

- [x] Guided setup creates an organization plus OWNER membership and activates that organization.

- [x] Guided setup offers only real starting paths: CSV import, manual inventory, or workspace exploration.

- [x] Customer-facing navigation exposes only real product functionality.

- [x] Login/signup/workspace/setup pages share the accepted Stewardence visual language.

- [x] Static assets resolve correctly in development and production collectstatic/WhiteNoise configuration.

- [x] Remaining rule-checkbox/file-input/footer polish is either corrected or explicitly judged acceptable for MVP.

- [x] Focused customer-entry tests pass.

- [x] Adjacent auth/workspace/rule tests pass.

- [x] Canonical suite passes at the phase gate.

**VERIFIED 2026-09-04 America/Chicago (2026-09-05 UTC).** Founder-created signup, guided setup and visual shell retained; naming and production-role registration fixes verified. See `docs/PHASE19A_CHECKPOINT.md` for exact tests and production boundaries.

## Phase 19B — deterministic evidence and local collector core

Required gates:

- [x] Stewardence defines a versioned deterministic evidence contract.

- [x] Evidence preserves detector ID/version, observation time, source locator/type, identifier, version/publisher where available, and evidence hash.

- [x] Evidence collection excludes passwords, cookies, saved credentials, browser history, and unrelated raw personal files.

- [x] Tenant-scoped discovery/evidence storage has forced PostgreSQL RLS equivalent to existing tenant data protections.

- [x] Repeated evidence ingestion is idempotent.

- [x] Historical evidence is not destructively deleted when absent from a later scan.

- [x] A one-shot Stewardence Collector runs on Windows without requiring a new Railway service/container.

- [x] The MVP Collector includes the minimum useful deterministic Windows/local detector pack.

- [x] Collector decisions are limited to observation/normalization. Risk and policy decisions remain server-side.

- [x] Collector submits/uploads a bounded deterministic evidence bundle to the existing Stewardence web service.

- [x] Ingestion strictly validates supported schema/version/size/hash.

- [x] A real Windows scan produces reproducible evidence for at least one supported local source.

**VERIFIED 2026-09-04 America/Chicago / 2026-09-05 UTC.** Evidence: `docs/COLLECTOR.md`; 19 focused Collector/ingestion/restricted-role tests passed, real Windows scan produced 222 observations, deterministic repeat check passed. Packaging, public artifact delivery, catalog reconciliation, automatic rules and report provenance remain later gates.

## Phase 19C — deterministic reconciliation and automatic rules

Required gates:

- [x] Collector evidence is reconciled through the existing deterministic catalog matcher.

- [x] Exact verified matches can reconcile into discovered inventory.

- [x] Conflicting exact matches go to review required.

- [x] Unknown evidence is not silently classified.

- [x] Repeated scans do not duplicate inventory.

- [x] Disappearance from the latest scan is represented without erasing history.

- [x] A versioned detector/product-to-rule mapping registry exists.

- [x] Applicable organization rules can be instantiated deterministically from supported detected inventory.

- [x] Detector-created rules preserve detector/mapping/inventory provenance.

- [x] Detector-created rules have a stable idempotency fingerprint or equivalent.

- [x] Human-created rules are never overwritten by automatic reconciliation.

- [x] Rules UI clearly identifies detector-created rules and why they were applied.

- [x] discovery.completed and reconciliation.accepted audit evidence is recorded using the existing audit system.

- [x] Cross-tenant discovery/reconciliation access is denied by application logic and RLS.

- [x] Adversarial/idempotency/tenant tests pass.

**VERIFIED 2026-09-04 America/Chicago / 2026-09-05 UTC.** Evidence: `docs/PHASE19C_CHECKPOINT.md`; exact verified product-name matches use the existing catalog matcher, unknown/conflicting evidence remains explicitly unresolved, discovered inventory and advisory rules are idempotent, latest complete per-device scans represent disappearance while retaining historical evidence, detector-rule lineage is visible and immutable through the UI, and same-tenant composite database constraints prevent cross-tenant evidence/rule references. The canonical restricted-role suite passed all 406 tests with 88.53% coverage. Production migrations were applied under `agentledger_owner` before deployment. Phase 19D delivery, snapshot/report lineage, artifact publication and end-to-end proof remain open.

## Phase 19D — evidence lineage, collector delivery contract, and freeze preparation

Required gates:

- [x] Assessment snapshots retain relevant sensing/evidence references.

- [x] Automatic-rule snapshots preserve rule provenance.

- [x] Report context carries evidence lineage without creating a second assessment/report architecture.

- [x] Report/user-facing provenance clearly distinguishes Observed, Declared, Catalog-derived, Calculated, and Unknown information.

- [x] Installed software alone is never treated as proof of a paid subscription.

- [x] Catalog capability is never presented as installation-specific observed permission without specific evidence.

- [x] Stewardence has a top-level Download path/page or equivalent canonical UI entry for Collector delivery.

- [x] Download architecture defines one Collector installer/bootstrapper plus a signed/versioned installation profile, rather than generating one executable per capability combination.

- [x] Collector module manifest architecture accommodates:
    - Microsoft 365 Intelligence
    - Google Workspace Intelligence
    - GitHub Intelligence
    - Accounting Intelligence
    - Browser Intelligence
    - Developer Tooling Intelligence
    - Continuous Observation
    - Desktop Portal

- [x] MVP does not present unavailable post-MVP modules as functioning controls.

- [x] Collector binary/artifact publication does not consume an additional Railway container.

- [x] MVP artifact publication uses the simplest secure/versioned external channel sufficient for first customers.

- [x] Artifact version and SHA-256 are recorded.

- [x] Real end-to-end proof exists:
    Collector scan
    → evidence ingestion
    → deterministic catalog reconciliation
    → inventory
    → deterministic applicable rule
    → assessment
    → PDF/report provenance.

- [x] Canonical suite passes.

- [x] Repository clean enough for release accounting.

- [x] Phase committed and pushed before Phase 20 continues.

**VERIFIED 2026-09-04 America/Chicago / 2026-09-05 UTC.** Evidence:
`docs/PHASE19D_CHECKPOINT.md`. The canonical restricted-role suite passed all 410
tests with 88.46% branch coverage. The founder-selected Helix Orbit source is
preserved byte-for-byte and only lossless crops are used. Production migration
`inventory.0007` was applied under `agentledger_owner` before deployment.

## Phase 20 — Railway production deployment

**VERIFIED UNDER FOUNDER-APPROVED MVP BACKUP AMENDMENT:** Production deployment,
release smoke, PITR, encrypted off-platform logical backup, and a clean restore
drill are verified. Railway scheduled-volume backups are unavailable on the
current trial plan and are deferred until first paying-client revenue funds the
required Railway plan upgrade. This amendment does not claim scheduled Railway
volume backups are enabled. Evidence: `docs/PHASE20_CHECKPOINT.md`.

- [x] 20.1: The owner-approved public GitHub repository exists, `main` is protected from force pushes, release candidates are tagged, and no secrets are committed. Repository visibility was explicitly changed by the founder.
- [x] 20.2: The Railway project and production environment exist with Railway PostgreSQL and no public database TCP proxy.
- [x] 20.3: Separate owner/app/worker database credentials are provisioned; long-running web and worker services never receive owner credentials.
- [x] 20.4: `web` is the only publicly reachable application service, binds Gunicorn to Railway's injected port, and uses `/readyz` as deployment healthcheck.
- [x] 20.5: `worker` has no public domain and reaches PostgreSQL privately.
- [x] 20.6: `renderer` has no public domain, exposes only its private application port, and receives no useful application secrets.
- [x] 20.7: The private `reports` bucket exists; only web/worker receive credentials as required.
- [x] 20.8: Production variables are present in Railway, secrets are not committed or copied into `.env`, and `.env.example` contains names only.
- [x] 20.9: Owner-credential migrations run only in a bounded migration operation, before incompatible code, using expand/contract compatibility.
- [x] 20.10: The Railway domain is fully verified before an approved custom domain is attached; customer outreach never uses a local address.
- [x] 20.11: Under the founder-approved MVP backup amendment, active/current PITR, an encrypted off-platform custom-format logical dump, and an actual clean restore drill are required before customer data. Railway scheduled-volume backups are unavailable on the current trial plan and are deferred until first paying-client revenue funds the required plan upgrade; they are not claimed enabled.
- [x] 20.12: A smoke test from an unrelated network verifies HTTPS, login, workspace, inventory, CSV, assessment, ROI, rule builder, browser/PDF reports, logout/login, authorized download, and cross-tenant isolation.
- [x] Production availability has no dependency on the founder's computer, WSL2, router, home Internet, or personal availability; Caddy is not deployed.
- [x] Railway deployment IDs are recorded as release evidence.

## Phase 21 — Demo data

**COMPLETE:** Production evidence is recorded in `docs/PHASE21_CHECKPOINT.md`.

- [x] Demo Bookkeeping Company contains the specified realistic manual inventory, including one unknown tool, without implying live connectors.
- [x] Demo scenarios cover payroll, banking, external transfer, missing approval, unknown retention, low risk, poor ROI, and strong ROI.
- [x] A polished demo assessment and PDF contain at least one genuinely justified Low, Moderate, High, and Critical finding.

## Phase 22 — MVP UX walkthrough

- [x] The real journey passes: anonymous visitor → signup → guided organization setup → Collector download/run → evidence ingestion → reconciliation → inventory → automatic rule provenance → assessment → report → stored/retrievable PDF. Manual inventory and CSV remain working alternatives.

- [x] The complete 18-step customer workflow passes without Django admin, including historical assessment retrieval after logout/login.
- [x] A small organization reaches its first useful manual assessment in under 30 minutes.
- [x] Required verbal explanations are recorded; repeated explanations are treated as UX defects.

Phase 22 evidence, 2026-09-06: a disposable production account and organization were created through the deployed Railway web UI, not Django admin. The walkthrough used the production deployment, production report `AL-2026-000005`, and production assessment snapshots for Low risk / strong ROI and Critical risk / poor ROI scenarios. Controlled Collector evidence was generated from a disposable local virtual environment using synthetic registry facts only; no host inventory was uploaded. The video artifact `Stewardence-MVP-Production-Walkthrough.mp4` is H.264 1920x1080, 167.966667 seconds, SHA-256 `a3de41efcb6483ab5e89be74d121e3a4694b560aca5feeb5dae39a21d105a60a`, with the required demonstration watermark burned into every frame. The narrated artifact `Stewardence-MVP-Production-Walkthrough-Narrated.mp4` contains H.264 video and AAC audio, SHA-256 `13f36bb086de398d09eddafd1db0fb7551e4526f9ee19b5529d3d9457dcb2ebe`. Logout/login retrieval was proven after restoring the user workspace context and reopening production report `AL-2026-000005`; local proof frame SHA-256 values are retained in the full evidence manifest. The local full evidence manifest records sensitive account, deployment, local path, and raw frame details; the public repository records only sanitized proof metadata. The downloaded report PDF hash is `d16931184cf84ed9d4794a890b42c1441fa9c637f73c3f37da151278ca6bea97`.

Phase 22 is complete. The disposable login proof used a locally encrypted credential for the controlled walkthrough account; temporary plaintext and hash bridge files were deleted after use.

## Phase 23 — Final MVP release gate

- [x] The full automated suite passes, including tenant RLS, raw SQL, worker leases, rules, risk, ROI, CSV, snapshots, Merkle, renderer security, and report ownership.
- [x] Django deployment checks and repository production-security validation pass.
- [x] No cross-tenant data access is possible under the tested web and worker roles.
- [x] Identical assessment input produces identical output and identical input/ruleset/engine produces identical hashes.
- [x] Historical assessments remain unchanged.
- [x] Manual inventory is never silently overwritten.
- [x] Unknown products remain unknown.
- [x] The PDF matches its immutable assessment snapshot.
- [x] Worker crash recovery passes.
- [x] Report downloads are tenant-authorized.
- [x] Backup restoration passes on a clean target.

Phase 23 evidence, 2026-09-06: `docs/PHASE23_CHECKPOINT.md`. The canonical restricted-role suite passed 413 tests with 88.43% coverage after rerunning with an isolated temp root; Ruff lint and format checks passed; Django deploy check passed with only the accepted HSTS preload ramp-up warning; the production smoke test passed against the Railway deployment at commit `a012afca25edc90161e24299320819659cc8c3d4`, including signup/login, workspace setup, manual inventory, CSV approval, custom rule save, ROI, immutable assessment, browser report, private PDF, logout/login historical retrieval, and cross-tenant denials. Phase 20 already records PITR, encrypted off-platform backup, and clean restore drill evidence.

## Sellable MVP acceptance matrix

- [x] Authentication
- [x] Organizations and organization membership
- [x] PostgreSQL RLS
- [x] Manual AI/software inventory
- [x] CSV import with preview
- [x] Small deterministic product catalog
- [x] Accounting/bookkeeping rules pack
- [x] Deterministic policy engine
- [x] Deterministic risk engine
- [x] ROI calculator
- [x] Visual no-code rule builder
- [x] Findings and remediation UI
- [x] Immutable assessment snapshots
- [x] Browser report
- [x] PDF report
- [x] Audit trail
- [x] Merkle audit sealing
- [x] PostgreSQL background jobs
- [x] Tenant-isolation tests
- [x] Security release gates
- [x] Railway deployment
- [x] Verified backups
- [x] Health and readiness checks
- [x] Demo organization
- [x] Founder-assisted onboarding path

## Explicitly excluded from the MVP

Full Microsoft 365, Google Workspace, GitHub and Accounting connectors; full Desktop Portal; continuous/scheduled discovery and monitoring; persistent endpoint fleet management; browser extension product; SIEM; packet inspection; automated enforcement or permission changes; LLM discovery, classification, rule generation or risk decisions; subscription billing; additional industry packs; mobile application; Node backend; React SPA; Redis; Celery; RabbitMQ; Kafka; Elasticsearch; Kubernetes; Caddy; capability-pack marketplace; and arbitrary third-party plugin execution remain excluded. Public signup and user-initiated deterministic local discovery are now required founder amendments.

The Collector observes bounded evidence; the existing cloud application interprets it. Every downstream result must distinguish Observed, Declared, Catalog-derived, Calculated, and Unknown. Installation alone is not proof of cost or of installation-specific resource access. No additional Railway container is used for sensing or artifact publication.

## Freeze gate

- [x] Phases 19A–19D and original Phases 20–23 are verified under the amended scope, including the founder-approved MVP backup amendment. Deterministic sensing and automatic applicable rule creation are the final substantive MVP additions; after acceptance, product feature work stops.

- [x] All Phase 23 items and every Sellable MVP acceptance-matrix item are verified with durable evidence.
- [ ] Git tag `v0.1.0` identifies the frozen release.
- [x] The release record contains commit hash, migration head, dependency-lock hash, Railway deployment IDs, and date.
- [ ] Development has stopped except for defects that prevent security, correctness, onboarding, assessment, reporting, payment, or customer use.
- [ ] The project has switched from BUILD MODE to SELL MODE.

When and only when the freeze gate is fully verified, the controlling declaration is:

```text
MVP CODE FREEZE REACHED.
THE NEXT TASK IS CUSTOMER VALIDATION.
```
