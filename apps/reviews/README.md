# Review kernel candidate

The initial 0001 slice admits owner-bound review identities and freezes a
manifest from one verified immutable assessment snapshot. The closed 0002
successor below adds separately qualified lifecycle boundaries.

`open_cycle(organization_id, actor_id, input_snapshot_id, baseline_pack_id=None)`
creates an immutable cycle identity and its OPEN revision 1 event.
`freeze_cycle(cycle_id, organization_id, actor_id, expected_revision=1)` derives
the manifest on the database side. It atomically reserves capacity and appends
FINALIZATION_REQUESTED revision 2 and FROZEN revision 3. Identical freeze replay
returns the original pack identity and reservation. No supplied raw manifest,
decision selection, digest, price, billing interval or quota limit is accepted.

FROZEN means immutable input identity. With Decision Desk's operator gate off,
its manifest records empty initial decision selection. When that gate is on,
0002 selects exact snapshot/card-bound owner statement events server-side and
freezes them once. Later events do not change replay. No artifact and blocked
baseline promotion describe the state at freeze. A
non-null baseline is rejected until a separate complete-artifact promotion and
baseline compare-and-swap path is qualified. Snapshots are never edited.

Both issuers require the actual bound paid workspace owner, READ COMMITTED,
healthy/unpaused Core, and control-before-review-capacity-before-cycle locking.
The migration depends on jobs 0013 paid entitlement and billing 0006 coverage.
App raw insert/update/delete and worker table access are revoked. All five
tables force RLS; app reads require tenant and owner membership. Related state
properties are lazy database reads: callers must keep their owner/tenant context
active. An already returned model is not a transferable authority capability.

Internal admission bounds are one OPEN cycle and one frozen/artifact-pending
cycle per organization. Closed 0002 completion releases the pending-cycle bound
and records consumption through an append-only event. The separate 100 active
inventory-record limit is not a lifetime review-cycle cap and remains an
independent inventory admission gate. Capacity reserves 16 MiB and counts reserved/reconciliation/consumed
cycles against 12 slots per actual admitted service interval. Receipt identity
is retained, while grouping also binds subscription generation and interval to
prevent duplicate invoice receipts from resetting quota.

Storage admission counts recorded retained report-artifact bytes plus held
reservation bytes against 3 GiB. This is recorded metadata, not a scan of object
storage. Other artifact writers do not yet participate in the review capacity
lock: cross-product simultaneous storage consumption remains an open gate.

Reservations and their initial events are immutable. No timeout, arbitrary
cancel or app method can release them. Unknown outcomes remain held. Positively
proven unused release, reconciliation and consumption need separate narrow
issuers and evidence contracts. 0002 introduces consumption only; no arbitrary
release, timeout or reconciliation-resolution issuer is introduced.

New Enterprise functionality, services, provider writes and deployment gates are
unaffected. Isolated migration/test results do not establish deployed readiness.

## Closed lifecycle candidate (0002)

The new candidate adds ARTIFACT_PENDING and COMPLETED, immutable artifact
requests/completions, and a narrowly written baseline head. Its application
setting `REVIEW_PACK_LIFECYCLE_ENABLED` defaults false, the owner-operated
database switch defaults false. The candidate resolver always installs its
worker wrapper, and the worker command supplies the configured identity;
services remain stopped. These are qualification candidates, not live functionality.

Requests bind the existing one-report-per-snapshot identity, exact queued job,
pack digest, an explicit owner promotion choice, and observed baseline head.
An already rendered report or a report bound to another pack is unavailable;
repeat packs over the same snapshot need separately agreed report-reuse rules.
No frozen manifest is changed to describe later artifact or baseline effects.

`ReviewReportGenerationHandler` performs actual storage readback and digest/size
validation within the existing fenced persistence transaction. Its worker-only
issuer checks current paid/pause/lease authority and exact report/snapshot/job
binding. SQL cannot verify storage bytes by itself; a compromised trusted
worker could lie about readback. Local qualification is not live Spaces proof.
The initial 0002 qualification rendered an assessment report; it did not
establish frozen decision/exposure presentation. That qualification alone does
not establish a complete review-pack presentation.
Completion, artifact metadata, consumed reservation event and queue completion
roll back together. External objects can survive and require reconciliation.
Failures leave the same pending request/digest and capacity reservation held.

Promotion requires the frozen request's explicit owner choice and unchanged
observed head. Earlier cycle/snapshot or stale-head completion is recorded
without promotion. The completion receipt records the outcome. Non-null
baseline selection in `open_cycle` remains closed: this slice does not yet
claim a qualified review-diff or historical baseline-selection flow.

## Lease-scoped render projection candidate (0003)

The new worker-only projection binds current tenant/job/token/lease, paid/pause
authority and the closed lifecycle gate to the exact request/report/pack. It
verifies immutable snapshot input/result, manifest and each frozen selected
event/revision/card digest. It reads recorded event identities, never latest
decision history, and grants the worker no additional table access.

The trusted context builder checks legacy snapshot pins and ordered inventory
identities, adds exact statement/proposal payloads and exposure wrappers with
their original snapshot source records, and normalizes pure exposure results
to JSON primitives. Owner statements remain unverified. Ordinary reports keep
their existing context. The new context's renderer/HTTP/presentation integration
requires its own qualification; projection tests cannot establish PDF fidelity,
live storage recovery or deployment readiness.

The versioned exposure questions are derived at render time from the frozen
inventory inputs; they are not selected findings pinned by the v2 manifest.
The context uses the exact `core.exposure.declarations.v1` contract. Historical
rendering must retain that contract or use an explicitly qualified successor
identity, rather than silently changing past pack meaning.
