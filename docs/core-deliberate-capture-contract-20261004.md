# Additive deliberate capture contract — proposed

Read-only design, 2026-10-04. Self-service $99/month Core, optional assistance, broad audiences. No product edits, activation or release approval. Required first journey: paid owner -> reviewed tool record -> deliberate unknown-aware capture -> generic exposure/applicable proposals -> exact owner decision -> freeze -> PDF.

Read `evidence/lyra-frozen-projection-disposition-20261004.txt`: deliberate capture and applicability remain open; non-accounting customers explicitly retain generic exposure without accounting claims. Parent reports historical exposure-v1 dispatch and profile handoff qualified in 28 cases; this design does not independently rerun them.

## Minimal new contract

Add **snapshot schema 2**; never rewrite stored schema-1 inputs/results/hashes or reinterpret historical readers. Preserve assessment UUID/version, tenant, captured time, deterministic inventory order, evidence and rule/configuration/engine pins. Add versioned capture identity, server-captured organization industry and explicit applicability.

Use an exact `benefit_model: {state: "not_supplied"}` envelope in new input/result. Omit legacy `roi` rather than redefine it; no assessed item, assumptions, zero hours, savings, default amortization, calculated ROI percent or net value. Known declared expenditure remains separate from benefit. A supplied model is a later deliberately selected contract.

Represent unknown versus declared-none versus declared-value explicitly for relevant inventory fields, including approval and monetary cost. Existing model defaults must not become knowledge; omit/null unknown captured values under the new schema instead of relabeling zeros/false/empty as declarations. Detection/catalog match does not establish use or permissions. At least one reviewed tool is required for this first-review slice; empty inventory gets a truthful no-record state.

Applicability is server-derived: accounting/bookkeeping may use its versioned accounting pack; other industries get no accounting pack and explicit not-assessed scope. Generic exposure-v1 is available to all. UNKNOWN exposure is not automatically a policy FAIL. Missing/unqualified risk uses explicit not-assessed/null, never Low/0. Applicable organization rules need their own scope/evaluator binding.

## Source map and additive boundaries

| Boundary | Current assumption | Required successor |
| --- | --- | --- |
| Capture | `apps/assessments/snapshots.py:create_assessment_snapshot` requires ROI/item; `apps/inventory/views.py:inventory_roi_view` is the only browser capture. | New deliberate owner POST/service, CSRF, current paid/pause/profile admission, reviewed active inventory and stable retry identity. Capture record provenance before calculation; edits require a new capture. |
| SQL admission | `assessments/migrations/0002_snapshot_security.py` grants app **and worker** INSERT; its trigger prevents mutation, not arbitrary issuance. `assessments/models.py:save` checks hashes. | New migration/narrow schema-2 issuer; deny raw app/worker schema-2 insert, retaining legacy behavior until separately reviewed. Bind actor/org, DB clock, reviewed inventory version/content, exact contract and idempotency after waits. Correct digest alone does not prove issuance. State explicitly where policy evaluation remains trusted Python; SQL hash checks do not prove those calculations. No worker provider-table access. |
| Validation | `snapshots.py:verify_snapshot` checks content SHA. | Exact version-aware structure/input-result identity, provenance, inventory-result membership, applicability and benefit-state validation. Unknown schemas deny. Preserve historical schema-1 interpretation. |
| Freeze/projection | `reviews/migrations/0001_initial.py:review_snapshot_manifest` accepts schema 1 only; `0003_worker_pack_projection.py` reuses it. | New successor validator supports exact new schema, preserving old pins. New snapshot-2 packs use a new manifest/worker-projection identity if shapes/meaning change; pin capture/applicability/benefit plus permanent exposure-v1. Keep locks, reservation, current paid/lease controls and no direct worker table grants. Historical manifest-v2 dispatch is unchanged. |
| Context/PDF | `reports/context.py:build_report_context` requires ROI and integer risk/bands. `renderer/schema.py` closes AL-REPORT-CONTEXT-2, AL-REVIEW-PACK-CONTEXT-1, manifest-v2 and snapshot1. | Add exact new context/schema/template dispatch for benefit-not-supplied and policy/risk-not-assessed. Preserve old branches. No “ROI engines evaluated” claim. Update `reviews/context.py`, `reviews/jobs.py`, `reports/jobs.py` version dispatch before writes; keep independent renderer rejection/escaping. |
| Proposals | `jobs/migrations/0012_core_authority_successor.py:issue_action_cards` and `jobs/core_workflows.py` consume FAIL policy rows. | Validate applicable schema-2 rows before issuance. Generic-only capture may have no proposals and still freeze/export. Generic exposure actions, if required, need a separately named/versioned issuer/evidence basis, not counterfeit accounting FAIL cards. |
| Decisions | `jobs/core_decisions.py`/jobs0014 bind snapshot/result/revision/card. | Preserve exact immutable binding. No completed owner statement carries into changed snapshot/card. Generic owner note must not pretend to be an exact policy-card decision. |
| History/comparison | `reviews/comparison.py:compare_snapshots` accepts schema1 only and compares legacy ROI; browser readers assume old fields. | Add schema2 readers/comparison with applicability and benefit-state changes. Mixed1/2 may initially show explicit unsupported comparison while both remain readable; never coerce absent to zero. Baseline admission/promotion remains gated. |

## Implementation sequence and finite qualification

1. Define schema2 and unknown-aware intake/provenance. Preserve legacy fixtures. Settle reviewed inventory revision/receipt identity for review-to-submit races.
2. Add issued capture/owner POST and actual-role tests: same retry one snapshot; changed request/content denied; foreign tenant, viewer, unpaid, paused, post-lock expiry and raw schema2 insertion denied. No historical backfill.
3. Qualify all onboarding industries: accounting findings only where applicable; generic non-accounting exposure; explicit unknown/none/false/cost states; no invented permissions, risk or benefit. Settle evaluator trust boundary rather than overclaim SQL authority.
4. Add exact successor freeze/context/renderer dispatch and actual Chromium PDF. Require no ROI percentage/net savings or Low/0 proxy; retained historical rendering uses original contracts; unknown/mixed-invalid versions deny. Frozen owner decisions survive later events.
5. Qualify self-service complete journey, private tenant negatives, cancellation/expiry/export, then final-source regression. Live Stripe/storage/offsite restore/release gates remain separate. No mandatory invitation, assistance or manual intake review.

Open finite choices: exact successor manifest/context names; unknown monetary input semantics; trusted evaluator admission; generic proposal scope; mixed-schema comparison timing. These do not authorize live listeners, Enterprise or reinterpretation of historical snapshots.
