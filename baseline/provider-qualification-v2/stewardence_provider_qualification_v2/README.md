# Stewardence provider connection qualification

Run `python3 qualify.py` on the DigitalOcean host. Requires its existing qbo5-reports image, Docker and passwordless sudo. This creates a temporary test image, internal network and disposable PostgreSQL 18.6 database; production volumes, credentials and configuration are not mounted. Created containers/network/image are removed afterward. Logs stay in this directory.

## Candidate scope

- Microsoft: configured owner and Entra tenant only; delegated consent with PKCE, Graph organization identity check, encrypted tokens, manual renewal and account verification, local disconnect. Entra consent revocation is separate.
- Xero: one authorized Demo Company only; confidential Web OAuth, organization identity/Demo Company checks, encrypted rotating tokens, manual renewal and account verification, provider disconnect and clearly labelled local recovery if revocation fails.
- Both: one-use session/workspace-bound state; CSRF-protected operations; empty private callback redirects; bounded HTTP reads; no redirects or automatic transport retries; PostgreSQL forced RLS and immutable connection identity; append-only runtime event history; worker denied credential-table access.

## Qualification boundary

265 local connector and QuickBooks tests passed, one Xero-only case skipped for Microsoft. Local SQLite does not validate PostgreSQL RLS or billing concurrency. This server qualification includes provider, QuickBooks, billing, pricing, analysis and tenant-context regressions on PostgreSQL with restricted runtime roles. Live provider requests are mocked. A passing run does not prove live consent, live renewal, or public proxy callback privacy.

This is not a deployment. Provider preview settings default off. No paid entitlements change, worker start, report storage, scheduled collection, event listeners, or public cutover occur. Production deployment needs a backup, additive migration, read-only credential mounts, callback edge validation and owner-only enablement. Microsoft grant inventory and Xero report retrieval follow connection qualification; continuous monitoring remains Enterprise work.

The source manifest checks archive consistency; it is not a signature proving artifact origin.

## v2 correction
Only the unauthenticated-read test changed. It now accepts the exact SQLSTATE 42501 missing-identity denial or zero visible rows, and independently checks all three provider tables for both providers. Other database errors and exposed rows still fail. Application source, migrations and qualification runner are unchanged.
