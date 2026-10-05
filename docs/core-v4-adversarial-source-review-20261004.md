# Core v4 adversarial source review — 2026-10-04

Scope: read-only candidate source review during the integrated qualification
freeze. No production inspection, provider operations, migrations or attack
execution. The reported 20-case successor passed actual Chromium delivery,
private access and exact SQL/Python preflight; the new full-suite receipt is
pending. This document does not reopen previously qualified findings unchanged.

## New source-derived blocker: undeliverable frozen pack retains capacity

`source/apps/reviews/migrations/0006_capture_proposal_packs.py:162` freezes the
selected proposal and decision history, then commits a held 16 MiB reservation
and FROZEN state. Exact context construction and the 1,048,576-byte check occur
only in `request_review_artifact` at lines 394–398, in a later transaction.

A permitted workload can exceed that bound: 100 unknown-aware inventory records
can yield four generic proposals each; every proposal admits separate
disposition and execution statements; each statement admits 4,096-character
notes (`source/apps/jobs/migrations/0016_capture_decisions.py:48`). Notes alone
can exceed 3 MiB before JSON structure, repeated proposal identities and frozen
inventory are counted. This is a concrete admitted-size construction, not an
executed database counterexample. It does not require fabricated receipts or
raw metadata insertion.

The request correctly fails closed and rolls back its effects. The already
committed FROZEN pack and reservation remain. The freeze issuer rejects another
pending pack (`0006`, pending-capacity check), and no qualified owner operation
positively releases this known-unused reservation. Fresh capture therefore does
not repair the journey. This is tenant-local availability/resource exhaustion;
no cross-tenant access or provider-write claim follows.

Required qualification: issue a valid oversized statement population through
the admitted APIs; freeze; attempt request; assert no new Report/Job/request
effects and prove whether a subsequent fresh capture can freeze. Preserve the
existing exact byte comparison and original state assertions.

Minimal repair choices require a deliberate successor: (a) before freeze
effects, reject a provably oversized complete future context, preserving the
OPEN cycle; or (b) add narrowly qualified positive-unused reconciliation that
cannot release a reservation with admitted work, artifacts or an unknown
external outcome. The exact request preflight remains necessary either way.
Do not solve this by widening the renderer limit, truncating frozen statements,
discarding history, or instructing customers to delete inventory.

### Narrow positive-unused termination is the smaller honest repair

The current schema already has immutable cycle and reservation event histories.
A successor owner issuer can terminate an unused frozen cycle without changing
its manifest, proposal selection or reservation admission identity. Prefer this
to constructing hypothetical future report metadata under an unexplained size
margin. Exact freeze-time rendering preflight would require a deliberately
pinned metadata identity or a separately justified upper bound.

Proposed issuer: explicit original-owner intent, RC and exact tenant/actor
context; control → capacity → cycle serialization; lock identity/FK targets;
require latest cycle state exactly FROZEN and latest reservation state reserved;
require no ArtifactRequest, completion, Report for the snapshot, ReportArtifact
for that snapshot/report, or report-generation Job referencing such a Report.
An already admitted or ambiguous job/upload is categorically ineligible.
Stopping unused work should require current owner membership and immutable
creator binding, rather than an unexpired subscription: expiry must not remove
the owner's ability to stop an unused cycle.

Append a terminal cycle event and a reservation event `proven_unused`, with a
closed reason, exact pack/reservation pins and the independently checked absence
predicates. Keep all original rows and manifest digests. Do not return the cycle
to OPEN. Repeated exact intent should return the original receipt; changed intent
must reject. The existing pending-state filter naturally excludes a distinct
terminal state, and the storage-capacity query already consults latest
reservation events. The monthly admission query counts the original reservation
row; leave it untouched, so this termination releases concurrent/storage
capacity without refunding the admitted monthly allowance. Refund policy is a
separate commercial decision.

Negative qualification must race request versus termination under the common
control lock, reject any existing request/job/report/artifact or reconciliation
state, preserve original monthly count, deny raw app/worker writes and foreign
owners, allow owner stop after paid coverage expires, and prove a fresh capture
can subsequently freeze. Historical freeze replay may still return the immutable
old pack, but request admission must not resurrect its terminal cycle.

No database absence query proves absence of arbitrary external objects. The
positive-unused claim is limited to the admitted worker protocol: without any
committed Report/Job or request, that protocol could not start an external write.
Untracked operator objects are outside this claim. Any admitted work or unknown
outcome requires separate reconciliation, not this unused-only issuer.

Executed predecessor follow-up: `evidence/20261005T001449.185864Z` admitted four
explicit records, issued 16 generic proposals and 32 separate disposition /
execution events carrying 4,096 four-byte Unicode characters each, and froze
the actual manifest. Request then raised `Queue input exceeds admission bounds`
in `queue_canonical` at the v4 context-size assignment. The historical
canonicalizer (`jobs0010`) first limits `octet_length(jsonb::text)` to 1 MiB,
before emitting compact canonical JSON; therefore the later v4-specific
`maximum is 1048576` exception did not execute. This is an earlier failing-closed
resource boundary, not grounds to widen either limit. The full context duplicates
the selected statement array in manifest and projection; its two copies exceed
1 MiB even before the remaining context fields. The successor test explicitly
asserts these admitted byte sizes and the exact observed earlier exception,
then requires rollback, stop receipt and fresh-capture capacity recovery.
The predecessor's failure remains preserved; the stop/recovery portion of that
case was not reached in that run.

## Lock and authority assessment

Proposal admission (`reviews0005`) takes control then snapshot-proposal advisory
locks, prelocks actor/org/snapshot/capture/profile, independently recomputes
finite policy/proposal semantics, and checks current paid/profile/pause/gate
after those waits. Decision admission (`jobs0016`) takes control then exact
revision/card decision lock, prelocks the same identity/receipt targets and
prior event, then checks current authority before the append.

V4 freeze takes control/capacity, cycle, proposal and ascending card locks.
The common control lock serializes cooperative same-tenant admissions before
these different later orders. No demonstrated cooperative lock-order inversion
was found. Operator-held row locks remain a separate wait surface; final
authority checks are necessary even when cooperative paths serialize.

V4 request prelocks gates, actor/org, snapshot, pack, receipt, report and job;
the original-creator predicate binds capture/proposal/revision identities.
The generic SQL-only request issuer may wait on cycle/head rows, but the v4
wrapper checks current authority after it returns. A failed later check rolls
back the entire enclosing database transaction. No stronger all-owner
ownership-transfer semantics should be advertised: the current subscription
and same-creator slice intentionally qualify one admitted billing owner.

V4 completion prelocks identity/effect targets and delegates to the existing
generic completion protocol. That protocol locks cycle/job and baseline head,
then checks paid/pause/lease after the final head wait. The v4 wrapper checks
the lease target and proposal authority again after delegated effects; failure
rolls back those database effects. No additional authority bypass was established
by this source review.

## Transaction and resource claims to keep precise

`source/apps/reviews/services.py:49` encloses Report allocation, job allocation
and SQL request admission in one identity/tenant transaction. The size rejection
rolls those newly staged database objects back. A direct SQL caller's previously
committed Report/Job is not erased by that rejection.

`source/apps/reviews/jobs.py:155` persists artifact metadata and runs verified
storage readback before protected completion inside the fenced worker
transaction. SQL verifies admitted metadata identities and digests; it does not
read PDF bytes independently. External objects written before a later database
failure can survive rollback and require reconciliation. No automatic storage
recovery or proof of production conditional-object semantics follows from local
Chromium/storage success.

The 1 MiB bound limits the admitted render context, not all snapshot/proposal
computation, report-object retention or every earlier JSON operation. Per-field
and per-record bounds alone are not a complete aggregate resource qualification.
All operator and application deployment gates remain closed pending release
qualification.
