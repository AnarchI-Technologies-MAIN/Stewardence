# Core paid entitlement successor — proposed, not implemented

Current snapshot: `20261003T235918.400817Z`. Core `grants_access` accepts
active/canceling status without a future paid period. Database workflow
entitlement has the same omission. Checkout admission now verifies a completed
paid session, registered price and a future subscription period; ongoing
renewal authority still needs qualification. A subscription period by itself
does not prove that a renewal invoice was paid.

## Authority and evidence

Use one explicit entitlement decision contract across middleware, protected
views, workflow admission, claim and persistence. Inputs must identify customer,
owner/workspace binding, admitted portfolio/price phase, subscription identity,
status and a verified entitlement interval. Compare expiry with the server's
current clock, not a caller-supplied scheduling time. Missing or contradictory
evidence returns a held/pending state with a safe recovery reason.

Separate provider-observed subscription status/period from the entitlement
interval issued from verified payment evidence. Record the exact qualifying
event/invoice/session identity, contract version and period. A digest or a
signed webhook does not by itself establish that an arbitrary subscription
update paid an invoice. Do not extend paid access from a scheduled collection,
locally invented timestamp, unknown historical period or a trialing state.

New standard Core requires its admitted USD 99 monthly contract. Preserve
already admitted founder phases and their exact reservations; no new founder
allocation. Automation sales and workers stay disabled. Coupon, credit,
proration, tax, partial-payment and plan-transition semantics require explicit
supported contracts; unsupported combinations enter review rather than silently
being converted into the standard offer.

## Bounded qualification matrix

| Trigger | Required behavior |
| --- | --- |
| Valid issued paid interval, active | Owner receives entitled Core access |
| Valid paid interval, canceling | Access lasts through the admitted interval only |
| Expiry at/before server time | Protected work and queued report claims held |
| Missing period or payment evidence | Held as unverified; no fabricated backfill |
| Trialing, incomplete, unpaid, unknown status | No new paid entitlement |
| Update with unrelated customer/subscription/price | Reject transition; preserve auditable reason |
| Subscription period advances before paid invoice | Do not advance issued paid access |
| Qualifying renewal payment | Advance once, through exact admitted interval |
| Duplicate payment delivery | Same issued result; no second transition |
| Older event after newer entitlement | No rollback/extension outside defined event order |
| Current paid renewal followed by stale failure | Do not revoke solely on an older unrelated invoice |
| Refund/dispute/cancellation | Explicit policy transition; no inferred financial authorization |
| Owner pauses after lapse | Stop control remains available without paid entitlement |
| Period expires during execution | Persist/completion rechecks fail closed; reconcile external object |
| Raw worker SQL after lapse | Existing narrow issuers still enforce current admission |
| Recovery retry after lapse | Preserve job/receipt evidence; hold execution until valid admission |

Use actual app/worker database roles and deterministic barriers for claim and
persistence tests. Assert exact-boundary expiry and unverified-NULL cases.
Exercise current SDK objects and real locally signed fixture envelopes, plus
receipt rollback and replay. These are offline controls; real Stripe delivery
and account verification remain separately deferred.

## Migration and release gates

Add a new reviewed successor migration; do not edit historical migrations or
deployed rows. Identify historical subscriptions lacking verified periods in a
read-only preflight. Reconcile them from authorized provider evidence before
cutover; never assume active rows are paid or synthesize future dates. No
operator backfill, provider call, production migration or activation is
authorized by this plan.

Update synthetic test fixtures explicitly when they intend to represent paid
customers. Keep tests for missing/expired evidence as negative cases; do not
add a test-mode entitlement bypass. Owners must retain account/billing/recovery
and pause access needed to resolve a held state.

Require exact final-source qualification, scoped Lyra review, a concrete
rollback/reconciliation package and Alexander's final production approval.
The earlier worker-claim intermittence remains a separate unresolved gate.
