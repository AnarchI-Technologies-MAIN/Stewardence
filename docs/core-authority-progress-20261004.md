# Core authority successor: implementation and qualification

Production remains unapproved and unchanged. This document records local
candidate work; it does not replace historical evidence or authorize release.

## Implemented boundaries

- Immutable paid coverage, account/mode and exact contract pins, dedicated
  `agentledger_billing_admission` principal, and narrow database issuers.
- Separate ingester authenticates the original Stripe signature and retrieves
  exact provider observations. Coverage, projection and receipt commit together.
  Database admission trusts this principal; a digest does not prove payment.
- Current paid access consumes issued coverage at server time. Observed status
  or a future subscription period alone cannot grant access. Unexpired issued
  coverage survives a failed-renewal `past_due` projection.
- Existing private report reads have a distinct ninety-day export predicate;
  new paid work remains blocked after expiry. Owners retain pause access.
- Initial review-cycle kernel freezes a server-derived immutable manifest and
  reserves capacity atomically. FROZEN does not mean a report was delivered.
- Standard checkout intent freezes a generation and exact request. Observation
  is not payment or authoritative expiry; ambiguous outcomes retain the intent.

## Bounded evidence

| Evidence directory | Result and scope |
| --- | --- |
| `20261004T190603.447642Z` | 29 issuer/paid-authority cases passed |
| `20261004T192504.258569Z` | 23 separate-login ingester cases passed; provider reads mocked |
| `20261004T192255.403098Z` | 33 initial review-kernel cases passed |
| `review-wait-counterexample/20261004T192508.441363Z` | Same actual-role barrier fails before repair and passes afterward |
| `20261004T192434.234099Z` | 63 protected-work, expiry and terminal-generation cases passed |
| `20261004T192615.587373Z` | 24 initial-checkout concurrency and invoice-contract cases passed |
| `20261004T193600.809638Z` | 15 standard checkout-intent cases passed |

Each directory binds a frozen source manifest, image and named JUnit receipt.
These executions cover different source snapshots; counts must not be added
into an invented final-source qualification.

The full snapshot `20261004T192706.940742Z` failed: 1,444 passed, 24 failed,
one setup error and one intentional skip. Legacy paid fixtures, scoped-table
expectations and protected-ledger cleanup require explicit reconciliation.
The historical identity and actual Chromium failures passed in this run;
their original causes remain unresolved and this failed suite closes neither.

## Review and remaining release gates

Lyra accepted the billing authority within its tested scope. Her visible review
is saved as `evidence/lyra-billing-authority-disposition-20261004.txt`.
Committed replay after issuance configuration changes is a successor under
qualification. Fresh-generation resubscription, provider checkout integration,
frozen customer-create requests, review artifact lifecycle/baseline CAS,
Decision Desk binding, retention enforcement, real Stripe test-mode delivery,
object restore, credential isolation and the golden journey remain open.

AGENTS.md is preserved exactly under Alexander's no-modification instruction.
Lyra's expanded release-authority wording applies operationally: production
migrations, deployment, service activation, provider writes, live payments,
campaign publication and cutover each require qualified evidence, scoped Lyra
production review and Alexander's explicit final approval. Development
authorization grants none of those production actions.

## Successor progress (20:05 UTC)

- `20261004T193754.833340Z`: 62 cases passed, including exact committed
  payment-event replay after cancellation, provider outage and issuance-pin
  changes. Replay acknowledges an existing effect; it does not grant new work.
- `20261004T194215.658839Z`: 87 reconciled onboarding, billing and RLS cases
  passed. Positive fixtures explicitly issue synthetic coverage; status-only
  draft subscriptions remain unauthorized. This is not a clean full suite.
- `20261004T195432.227991Z`: 62 Decision Desk/review cases passed, including
  exact-card binding, owner-only reads, concurrent revision admission and
  frozen-selection replay. Completion is an owner statement, not remediation.
- `20261004T195823.856812Z`: 65 lifecycle cases passed, including database-clock
  lease expiry while waiting for a baseline-head row. The before/after
  counterexample is being qualified separately.
- `20261004T195449.636979Z`: 15 standard-checkout service cases passed with
  mocked Stripe SDK writes, frozen customer/session requests, lost responses
  and concurrent retries. `20261004T195444.622732Z` separately passed 34 route,
  checkout and paid-work cases. A real routed durability test remains pending.

An integrated successor run is underway. A preceding invocation named two
nonexistent test files and ran zero cases (`20261004T200106.006474Z`); that
invocation failure is retained and provides no qualification evidence.

The lifecycle-qualified PDF still uses the ordinary assessment context. Frozen
decisions and exposure questions are not yet delivered in that PDF. A distinct
closed renderer contract and lease-scoped projection are under development;
worker table privileges will remain restricted. Review comparison, physical
retention, complete UI delivery, fresh-generation resubscription and the real
Stripe lifecycle remain open. Accounting-specific rules currently apply beyond
the intended industry scope; generic audience publication needs an explicit
qualified applicability contract. No production approval follows from these
bounded results.

Lyra subsequently closed `BILLING-REPLAY-01` for the exact submitted successor;
the visible disposition is preserved in
`evidence/lyra-committed-replay-disposition-20261004.txt`. Her production
disposition remains unapproved. Do not reopen that closed finding unchanged or
extend its acceptance to resubscription or complete ReviewPack delivery.

The integrated run `20261004T200136.759418Z` passed 141 cases but had 29 setup
errors: the paid-authority negative fixture reused a helper that had started
issuing coverage automatically. That created the singleton authority before the
fixture attempted its own explicit setup. The successor fixture opts out of
automatic coverage, preserving status-only denial and empty-ledger assertions.
An integrated rerun is pending; the failed receipt remains retained.

`20261004T200344.997008Z` passed four routed checkout durability cases under the
actual app role. An independent database connection observed committed frozen
customer/session requests before every mocked provider write. Lost-response
retries retained exact bodies and keys. This does not qualify real Stripe,
public TLS or browser CSRF behavior.

The causal baseline-head comparison is retained under
`evidence/review-head-wait-counterexample/20261004T200051.852194Z`: identical
actual-worker barrier admits after lease expiry in the immutable predecessor
and denies in the repaired image. No completion, artifact, reservation
consumption or baseline advancement occurs in the denied successor case.

## Integrated authority and customer-visible successor

`20261004T200631.243114Z` passed all 174 integrated authority/checkout cases,
with no errors or skips. The corrected negative paid-authority fixture remains
uncovered until its test explicitly issues payment evidence. This frozen source
includes an early projection migration; it does not qualify later rendering,
privacy or UI edits. A complete-suite successor is running separately.

Lyra closed the submitted lifecycle/Decision Desk scope, including frozen
selection, local verified completion, baseline CAS/order, successful reservation
consumption and restricted-table authority. Her visible disposition is stored
as `evidence/lyra-review-lifecycle-disposition-20261004.txt`. Customer-visible
projection, retention and production remain open.

The standalone ReviewPack renderer passed 55 cases, including actual Chromium
PDF text and inert customer content (`20261004T201136.065965Z`). The integrated
worker projection/context/storage/completion path passed an 80-case successor
(`20261004T201500.191024Z`); the final negative controls and exported visual PDF
are qualifying separately. No external object service was involved.

Five strengthened actual SIGKILL stages passed under restricted worker roles
(`20261004T201001.794794Z`), and rollback/concurrent recovery controls passed
two cases (`20261004T201156.344092Z`). Historical causes remain unknown;
`docs/core-historical-qualification-findings-20261004.md` records finite proposed
current-candidate stability gates without rewriting history.

New privacy finding: ordinary report viewer permissions would otherwise admit
owner-only ReviewPack bytes. A successor report migration adds restrictive app
SELECT policies using an authoritative owner-principal classification function;
viewer-hidden review rows cannot yield a false-negative classification. Actual
role and routed negative qualification is pending. Worker grants are unchanged.

Pure snapshot comparison now distinguishes inventory, finding, rule/config,
evidence-reference and ROI-input changes, with pinned content digests. Nine
comparison and ten exposure tests passed locally; this helper does not establish
baseline admission or causation. Owner UI is under development behind a closed
flag. Existing review baseline admission remains closed.

## Parallel qualification update

The complete frozen run `20261004T203524.475441Z` reports 1,715 passes,
four failures and one intentional skip. Two browser cases precede the corrected
pre-render fixture; two ordinary-report isolation cases omit authenticated-user
context required by the new read-authority function. The latter are undergoing
fixture and missing-context negative qualification; no privacy guard is relaxed.
This full run does not qualify later source edits.

Separate frozen successors passed 101 runtime/render cases
(`20261004T203409.204974Z`), 86 UI/render cases
(`20261004T203551.145004Z`), six owner-read privacy cases
(`20261004T202335.571899Z`), and 84 post-format lifecycle/projection cases
(`20261004T204824.067533Z`). These counts overlap and must not be summed.
Actual Chromium delivery selects the frozen decision, excludes its later live
successor, verifies local stored bytes, and completes through the runtime handler
factory. Six exported PDF pages were visually inspected. No worker was activated.

The proposal identity rejection reproduced in a later 31-case UI run. A subsequent
instrumented run passed; causal diagnosis remains open. Synthetic diagnostics
record every admission predicate, exact timestamp round trips, roles and clocks.
Admission predicates and production authority remain unchanged.

The next scoped Lyra packet is
`evidence/lyra-frozen-projection-delta-20261004.txt`, SHA-256
`c88a1f7aa6947f625edb9e644ab674bbea5db4b3e4f7598316c9b170b5ea442c`.
It supplies executed frozen source, context specimen, rendered visual receipts,
privacy negatives and the failed full-run status. Review is pending; production
remains unapproved. Exposure version 1 derives from frozen inputs and is not the
original assessment policy result. Its historical regeneration/version pinning
remains an explicit design limitation.

## Historical semantics and clock finding

Lyra accepted the submitted projection/privacy/runtime scope, then closed
`EXPOSURE-PROJECTION-VERSION-01` for the permanent v1 dispatch successor.
Historical `review_pack.v2` uses `exposure_v1.py`, independently of the current
public alias. Unknown manifest versions reject. Semantic changes require a new
implementation and admitted pack schema. The module is historical protocol code.
The explicit workflow-profile navigation handoff was also accepted. Neither
closure grants production approval or claims deliberate snapshot capture exists.

The exact successor passed 28 cases (`20261004T210715.617238Z`). Its earlier
85-pass/one-failure run compared tuple-bearing Python values against JSON lists;
the repaired test compares exact canonical RFC 8785 bytes. Failed evidence remains.
Dispositions are stored in `evidence/lyra-frozen-projection-disposition-20261004.txt`
and `evidence/lyra-historical-exposure-handoff-disposition-20261004.txt`.

Three synthetic inside-issuer failures now identify only `effective_future` as
true; all eleven other rejecting predicates are false and timestamp round trips
are exact. Python and PostgreSQL share a backward wall-clock step of about
0.73–0.77 seconds. The issuer correctly denies future-dated requests. Lyra closed
logical issuer ambiguity and named the infrastructure gate
`HOST-CLOCK-DISCONTINUITY-01`; no future-time allowance or timestamp subtraction
was added. Explicit diagnostic tests no longer run in ordinary collection.

The user-authorized reversible mail time-sync trial retained 64-second windows
with six backward steps before stopping, two while stopped and three after
restoration. The service is restored and verified active. This does not prove
mail is the sole cause. Subsequent read-only inspection shows Ubuntu chronyd runs
with `-x`, so it is not a clock controller; a separate PHC-backed listener remains
under investigation. No permanent time configuration was changed.

Twenty sequential offline Chromium renders passed the bounded 100-record
specimen at concurrency one, on frozen image `afd7c85b...`, within the unchanged
60-second budget: 3.055–15.628 seconds, identical normalized bytes, complete notes
and references, zero accumulating zombies and no OOM. Evidence lives under
`evidence/core-renderer-stability/20261004T210523.108580Z`. This is renderer-only,
not maximum customer capacity, admitted storage delivery, or historical timeout
causation. Core first-review capture and unknown inventory semantics are the next
candidate implementation slice.


## Explicit declarations and deliberate capture candidate

Explicit inventory passed62 focused cases on frozen `20261004T214030.821313Z`; omitted answers normalize to Unknown/null, while deliberate none/no/zero retain Declared provenance. Raw app/worker mutation, spoofed ownership, closed gates, pause and silent legacy conversion are denied. Both deployment and SQL operator gates remain false.

Capture schema2 passed87 cases on `20261004T215002.672491Z`, image `dd2fa93e6216275f40ed86eef36cf59861e05d4e3e1d8eb7e4cba62c034502a5`:50purecontract,29actual-role capture and8historical snapshot cases. This includes replay convergence and revocation during organization/actor-row waits. Additional boundary tests are pending; this is not current full-source qualification. Trusted Python computes policy; the SQL issuer binds live reviewed inputs, provenance/applicability, identities and digests, not independently recomputed policy truth. Legacy default values are not promoted. No benefit model or risk score is supplied.

The owner signed-preview/POST UI, legacy-report-route fences and additive schema2 freeze/render successor are under qualification. Until those qualify, schema2 preview links do not advertise proposal issuance or PDF freezing. The existing historical pack schema2/exposurev1 path is preserved; the proposed new pack schema3 is a separate contract. Initial new captures have empty decision selection, so the complete Decision Desk customer journey is still open.

The extended clock trial restored mail time-sync and remained discontinuous in all six stopped windows. Lyra accepted this as negative causal evidence; HOST-CLOCK-DISCONTINUITY-01 remains open. Read-only RAW-clock correlation measured adjusted clocks about5.5percent faster than RAW in one window. Setter attribution is unknown. No time guards/configuration were relaxed and production remains unchanged.

## Capture delivery and legacy issuer successor

Integrated frozen receipt `20261004T222559.192446Z` is **1,892 passed, 11 failed, one intentional skip**. Its disposition identifies each failure and preserves the original evidence. The customer HTTP flow reached a queued report, but the full run was not green. An earlier canceled qualifier briefly overlapped; no performance conclusion assumes wholly serialized execution. Future qualification containers now have explicit ownership names, labels and cleanup receipts.

Predecessor `20261004T224536.317608Z` executed the legacy proposal bypass: direct app SQL accepted schema2 capture on the schema1 issuer. All30RLS tests passed. Additive jobs0015 renames the exact old body to an owner-only helper and introduces context-first schema1 dispatch. Successor `20261004T225131.635655Z`, image `311dbf563e0535cfecfbb780de6f0393301947cfde6d581a490aa23774eba71c`, passed206cases including all9fence cases, all30RLS regressions, strict-CSRF first-owner journey, real capture worker Chromium/storage/completion/owner download/viewer denial, deliberate capture UI and golden historical hashes. Two synthetic archive fixtures still failed by trying to insert an already-completed job; subsequent legal fixture transitions await qualification. This remains a failed receipt, not full-source qualification.

Lyra accepted the fence's source design and requested `LEGACY-ISSUER-DEPENDENCY-BYPASS-01`: renamed-function OID dependency inventory, textual stored-procedure references, exact helper ACL and effective privileges across the complete provisioned runtime-login set. New bounded tests are prepared. Historical capture extraction needs its separate source/golden packet before reviewer closure.

Capturev1 now pins permanent inventory field/provenance vocabulary, profile validation, AL-POLICY-1 engine and accounting1.1.0 definitions. The compatible public entrypoint reexports v1; frozen context dispatch calls it directly. Generic/accounting golden hashes match predecessor source after mutable current aliases are replaced. This protects historical interpretation, not input truth, external library compatibility or production approval.

Pure proposal v1 is implemented but unintegrated: finite evidence/declaration requests and declared-boundary concerns, qualified accounting FAIL with frozen applicability, stable UUID/digests and immutable source outcomes. The new database issuer, exact-proposal decisions and packv4 remain pending. Initial packv3 still freezes empty decisions and cannot be advertised as the finished Decision Desk journey. No deployment/operator gate has been enabled.

## Reviewer scoped closures, 23:24 UTC successor packet

Lyra closed the installed-catalog legacy issuer dependency/ACL boundary and permanent historical capture-v1 interpretation from the frozen 23:14 qualification. The 147-pass/5-fail run remains failed overall; proposal issuance, Decision Desk v2, pack v4 and production remain unapproved. Disposition: `evidence/lyra-legacy-capture-closure-disposition-20261004.txt`. Future database callable paths must repeat the helper dependency/ACL audit.
