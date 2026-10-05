# Stewardence Security Invariants

**Authority:** SPEC-1-AgentLedger-v1.8 plus the owner-approved Railway hosting amendment. These are release gates, not aspirations.

## Tenant and identity boundary

1. PostgreSQL RLS is the authoritative tenant-data boundary. Django organization filters remain defense in depth, not the authority.
2. The normal web role is NOSUPERUSER, NOBYPASSRLS, and does not own tenant tables.
3. The normal worker role is NOSUPERUSER, NOBYPASSRLS, and does not own tenant business tables.
4. The owner role is used only for bounded provisioning/migration operations and is never a long-running web or worker credential.
5. Every tenant-owned row has a non-null organization UUID. Every tenant-owned table has RLS enabled and forced with both read and write policy enforcement.
6. User identity and organization identity are separate transaction-local PostgreSQL settings. Tenant context is set on the exact database alias used by the operation.
7. Missing, malformed, stale, unauthorized, or incorrectly aliased tenant context fails closed.
8. A browser/session organization ID is an untrusted selector until current membership is revalidated.
9. Workspace activation and all state changes are POST-only and CSRF-protected.
10. Unfiltered ORM, direct primary-key access, raw SQL, inserts, and updates cannot cross tenants. Tests prove the actual restricted database identity with `SELECT current_user`.

## Deterministic authority

1. Unknown software is valid input but is never probabilistically classified as AI. It remains unknown and requires review.
2. Exact, type-aware AL-ID-1 matching is authoritative; fuzzy similarity cannot create an authoritative catalog match.
3. Policy results are deterministic and version-bound.
4. Risk results are deterministic, version-bound, and explain every contribution and floor.
5. ROI arithmetic is deterministic, exposes its inputs and formula, and safely handles zero denominators.
6. No LLM, current clock read, network call, executable expression, `eval`, `exec`, JavaScript, Python expression, or SQL expression participates in authoritative policy, risk, ROI, or approval decisions.
7. Customer rule JSON is validated structured data and contains no executable code.
8. Published platform and industry rules are immutable; a change creates a new version.

## Historical and audit truth

1. A report is generated only from an immutable assessment snapshot, never mutable live inventory.
2. Snapshot input and result hashes bind the canonical inputs, ruleset/organization-rule versions, engine version, risk configuration, and ROI assumptions.
3. Editing inventory, rules, or ROI assumptions cannot alter an existing assessment or report.
4. Manually confirmed inventory is never silently overwritten.
5. Audit event creation is independent of sealing so an unavailable sealer cannot erase history.
6. Merkle sealing commits the complete canonical event envelope with domain-separated hashes, stable ordering, and tenant-scoped chain heads.
7. Audit history is tamper-evident, not magically immutable. The UI must not claim blockchain protection, impossibility of modification, or unhackability.

## Background-work boundary

1. The PostgreSQL jobs table is the durable source of truth; LISTEN/NOTIFY is only a wake-up hint.
2. Job ownership is database-claimed and fenced. A stale worker cannot complete or fail a reclaimed job.
3. Retry timing uses attempts read from the locked row, not caller input.
4. Initial and periodic scans recover jobs that predate LISTEN or whose notification was missed.

## Reporting and object storage

1. The renderer has no public domain, database credentials, OAuth credentials, KEKs, or unnecessary bucket credentials.
2. The renderer accepts only validated structured report data and owns fixed templates. It accepts neither arbitrary customer HTML nor a customer-selected output path.
3. Chromium runs non-root with its sandbox enabled. JavaScript is disabled, service workers are blocked, and every browser request is aborted.
4. Customer strings are template-escaped; traversal and `file://` inputs cannot select or read local files.
5. Railway private networking prevents public inbound exposure between internal services but is not an outbound-denial control. Browser-level network denial and a secret-free renderer remain mandatory.
6. Reports are stored in a private object bucket, not an ephemeral service filesystem.
7. Report access requires authentication, current membership, tenant RLS, and report-ownership authorization before a short-lived presigned GET or authenticated proxy download. Knowing an object key or report UUID grants no authority.
8. Object metadata includes key, content type, SHA-256, size, report ID, creation timestamp, and snapshot ID.
9. Current Railway Bucket documentation states that API server-side encryption controls, object versioning, object locks, and lifecycle rules are not supported. This is an unresolved pre-customer security disposition, not a feature Stewardence may claim.

## Credential boundary

1. No Microsoft or Google connector—and therefore no production OAuth refresh token—is part of the MVP.
2. The connector-ready cryptographic module uses per-record DEKs, versioned KEKs, AES-256-GCM, unique nonces, and tenant/record-bound AAD.
3. Wrong tenant, record, or key authentication fails closed.
4. Normal and compromise rotation are distinct procedures. Old KEKs remain until no active envelope references them.
5. Credentials, KEKs, database owner passwords, bucket secrets, and Django secrets are never committed, printed, embedded in commands, or stored in `.env` as production truth.

## Product-claim boundary

1. Stewardence assesses and recommends. The MVP does not claim third-party enforcement, automatic blocking, token revocation, account disabling, permission changes, compliance certification, or guaranteed security.
2. Demo entries are manual inventory and never imply a live connector.
3. Health, container state, source code, or a local test does not alone prove production callable state.
4. A deployment healthcheck proves activation readiness at deployment time; it is not continuous availability monitoring.

## Release evidence required

Release is blocked unless restricted-role tenant tests, deterministic fixtures, worker lease/fencing tests, snapshot immutability, Merkle verification/tamper tests, renderer isolation tests, report-ownership tests, Django deployment checks, production smoke tests, and a clean backup restore drill pass. Evidence must identify the tested commit, dependency lock, migration head, environment, and date.
