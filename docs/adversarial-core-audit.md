# Adversarial Core audit

Scope: editable local candidate and disposable PostgreSQL roles. Production was not attacked, migrated or changed. Financial provider requests, payments, emails and external listeners were not exercised. This is a reproducible defect audit, not a certification or claim that all attack surfaces are closed.

## Reproducible weaknesses and fixes

| Surface | Attack | Hardening | Evidence |
| --- | --- | --- | --- |
| Receipt authority | Main application inserts a worker recovery receipt | Application role now has SELECT only; worker retains tenant-bound INSERT | Real application-role insertion denied |
| Database namespace | Temporary background_jobs table supplies forged tenant/attempt/state | Guard pins search_path and explicitly references public.background_jobs | Worker temporary-table spoof cannot bind a foreign-tenant job |
| Receipt contents | Recompute a valid digest over a fabricated input digest | Verify actual job organization, operation, input digest, payload schema and outcome fields | Self-consistent forgery rejected |
| Type confusion | Boolean True masquerades as attempt 1 | Exact integer type admission | Boolean attempt forgery rejected |
| Workflow input | None/string/number/naive timestamp | Typed timezone-aware datetime required | Malformed input raises controlled validation error |
| Future repository adapter | Absolute/traversing identifier reused as filesystem path | Reject leading slash, empty/dot/dot-dot segments and credential URLs | Traversal references rejected before adapter wiring |
| Branch identity | Invisible name or bidi/control-character identity spoofing | Reject blank and control/format/surrogate characters | Spoofing inputs rejected |

Full qualification after receipt/identifier hardening passed 888 tests with one skip. Subsequent owner-profile setup, contract, receipt and RLS qualification passed 52 checks; upload/intake/signup/setup qualification passed 31 checks. These subsequent changes require a new complete suite result before a final source-wide claim.

Additional findings addressed: owner-only persisted workflow-profile setup rejects CSRF, forged actor/tenant fields, viewer access and cross-profile settings. Recorded meanings are protected against ORM bulk update/delete as well as normal model changes. Initial selection uses an advisory transaction lock without granting the application UPDATE permission on organization identities.

Multipart uploads now have an aggregate file-stream budget before the normal memory/temporary-file handlers. Missing content length and new-file offsets cannot reset the budget. Existing CSV and collector domain limits remain enforced; the deployment proxy still needs a whole-request cap before public cutover.

## Remaining attack surfaces

- Public workflow socket is not yet exposed. Require owner/current-membership admission, receipt ownership and integrity checks, explicit capability/entitlement evaluation, bounded payloads and idempotent dispatch before opening it.
- Client scheduling, persisted invariant selection and action-card reassessment remain implementation work. Threat tests must cover cancellation/replay, duplicate ticks, revoked membership, late jobs, substantial-signal criteria and cross-profile reinterpretation before activation.
- Dashboards summarize recorded evidence. Recorded state cannot establish fresh service health; freshness/coverage must remain explicit.
- Recovery receipts are hashes over database-bound records, not signatures or proof against a compromised database owner. Do not elevate them into independent authority attestations.
- Live storage compatibility, encrypted live-source restore rehearsal, process-level crash injection, health controls and alert delivery remain operational gates.
- Atlas-aligned UI/browser accessibility verification remains open. Source/test success is not visual qualification.

Automation stays behind Core hardening gates. Core's limited client schedules and risk-triggered deterministic work are within the revised Core scope; live collection/listeners and provider writes are not enabled.
