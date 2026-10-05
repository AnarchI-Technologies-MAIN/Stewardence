# Core workflow expansion

Alexander expanded Core to include limited scheduled work, risk-triggered reassessment and a receipt-backed organization dashboard without live listeners. This supersedes the earlier plan that reserved every schedule for Automation. Automation remains gated behind Core hardening and adds collection/monitoring capabilities through the same versioned contract.

## Branch semantics

Business branches/departments and development/Git branches are supported concepts. During setup, a client selects the appropriate invariant profile and its purpose-specific settings. Other meanings require a registered schema. Never silently interpret one profile's settings as another's. Each evidence record, schedule, action-card revision and metric must retain its profile/version reference; a future configuration change does not rewrite historical meaning.

Local schema validators define `business.v1` and `development.v1`, reject mismatched settings, spoofing controls, credential-bearing repository references and traversal identifiers, and provide UUID-bound evidence-directory categories. The local owner-only setup route now persists the initial selection. Database actor/membership guards and immutability prevent spoofed decisions or silent reinterpretation. A reviewed version-transition mechanism and atlas-aligned UI verification remain open.

## Shared operation entrypoint

The local `stewardence.workflow.v1` envelope defines tenant identity, operation, selected receipt identities, effective time and invariant profile with a canonical input digest. Core operation names are report generation from receipts, action-card reassessment from admitted signals, and health checking. This is a schema contract, not an exposed socket or an authorization decision. Transport, tenant/owner admission, receipt verification, dispatch and idempotency require separate implementation and qualification.

Automation adapters can later publish admitted evidence into the same contract. Deterministic validation and reassessment remain alongside them. Changing portfolio must never grant provider writes, replace tenant boundaries, or upgrade an observation into verified truth.

## Required workflows

1. Client explicitly selects report inputs, time zone/recurrence, recipients/access scope and schedule. Tick workers enqueue deterministic work with an idempotency key for each occurrence; missed runs, cancellation and DST behavior must be defined. Core does not fetch fresh provider financial data for these schedules.
2. A admitted risk signal passes source/tenant/schema/receipt checks and versioned substantial-change criteria. It marks only affected action cards for reassessment. A bounded tick consumes these triggers, creating immutable proposal revisions with input/output receipts. No listener or external action is implied.
3. Organization dashboards aggregate admitted services, selected branch profile, declared AI/agent/employee accounts and related evidence. Counts and metrics show source, unit, coverage and freshness; missing populations remain unknown. Directory categories are logical organization-scoped namespaces, not arbitrary client filesystem paths.
4. Recovery procedures classify known transient failures, preserve evidence, maintain bounded retries, emit append-only receipts and surface review holds. Health controls/circuit breakers and alerts must distinguish recorded conditions from fresh probes. In-app alerts precede any separately configured outbound notification.
5. Live-source backup/restore rehearsal runs against an isolated target; crash qualification injects failures into that isolated environment. Production restore, service activation and cutover require the final reviewed release package. No extra Droplet or paid service is implied.

## Implemented locally in this increment

- Append-only recovery receipts with forced tenant RLS, database-enforced job/attempt/outcome binding, canonical digest and verification. Worker outcome and receipt are written in one transaction.
- Core operations dashboard with recorded workflow counts, in-app review alerts, verified receipt history and private/no-store responses. It explicitly does not claim live service health.
- Versioned workflow/branch contract validation and logical evidence-directory taxonomy.

64 scoped checks passed after these additions, including real application/worker role isolation and database immutability checks. New receipt migration has only run in disposable local qualification databases. Current visual reference: visual-source-contract.md.

Open: profile version transitions, schedules and workflow charts, action-card model/reassessment, declared-entity intake/metrics, circuit breakers/probes, receipt-backed review/resume controls, live-source restore/crash qualification and atlas-aligned rendered UI verification.
