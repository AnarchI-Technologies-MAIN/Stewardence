# ROI-free capture → review pack adapter map

Read-only source map; names below are proposals, not implemented contracts. Capture source inspected: `apps/assessments/capture_contract.py`; review migrations 0001–0003, review context/jobs/exposure, reports context/jobs/services, renderer schema/template. No product or historical migration edits.

Implementation follow-up: the separately authorized bounded capture adapter now emits the closed five-key context `{context_version, title, metadata, projection, exposure_reviews}` under `AL-REVIEW-PACK-CONTEXT-2`. Its standalone renderer uses a separate capture template. The proposed `stewardence.review_pack_render.v2` wrapper and standalone `AL-REPORT-CONTEXT-3` were not implemented in this slice. The worker uses the admitted projection directly, avoiding legacy report construction only for projectionv2; historical preparation remains unchanged. Selected decisions are explicitly empty, and baseline promotion remains blocked. This is a capture/report milestone, not the complete Decision Desk/comparison customer journey. Purpose text is now bounded to 4,096 characters by the capture contract. The coordinated SQL successor and actual worker lifecycle qualification are separate gates.

## Current boundaries

`build_capture_payloads` emits snapshot schema **2**, exact declaration contract `core.capture.declarations.v1`, explicit provenance and frozen workflow settings. All records have risk `{state: not_assessed, score: null, band: null}`. Benefit model is `{state: not_supplied}`. Generic exposure applies across supported industries; accounting alone admits its pinned industry policy definitions/results. Accounting policy findings do not establish a numerical assessed risk score.

ReviewCycle already references AssessmentSnapshot, so capture2 stored by a separately authorized issuer can reuse the existing identity relation. No new polymorphic snapshot relation is necessary for this slice.

Blocking assumptions:

| Boundary | Current assumption | Additive successor |
|---|---|---|
| 0001 `review_snapshot_manifest` | Input/result snapshot schema1; rules/config/engine objects; current profile lookup | Exact capture2 branch with admitted capture authority, frozen profile/settings and both hashes |
| 0001/0002 `freeze_review_cycle` | Generates `stewardence.review_pack.v2`; selected legacy Core decisions | Generate pack v3 only for admitted capture2; preserve recorded existing pack replay |
| 0003 `review_pack_projection` | Pack v2 + snapshot1; verifies decision revision/result bindings | Separate capture2 projection branch, same lease/tenant/identity/hash checks |
| reports `build_report_context` | Integer score, known Low/Moderate/High/Critical band, input/result ROI mappings | Explicit snapshot2 dispatcher before historical builder |
| reviews `build_pack_context` | Deep-copies legacy report context; exposure permanently dispatches v2→v1 | Separate packv3 builder over reportcontext3; explicit declarations exposure |
| renderer schema/template | Only reportcontext2/reviewcontext1; legacy risk/ROI fields and one template | Separate closed capture report/review schemas and version-selected template |

Important: `ReviewReportGenerationHandler.prepare` calls `delegate.prepare` before adapting a projection. Merely adding SQL projection/schema3 will still fail in legacy report construction. A report-context dispatcher is required upstream of that call, or a separately qualified preparation path producing the same immutable ReportGenerationPrepared identity envelope.

## Proposed exact interfaces

- `app_private.review_capture_manifest_v1(snapshot_id, organization_id)` — narrow owner SECDEF helper verifying capture2 admission receipt, snapshot tenant/actor/assessment/version/date, exact payload contract and canonical hashes. Return the same snapshot identity pins plus capture contract, industry applicability, frozen workflow settings hash and engine versions. Current mutable workflow-profile settings must not reinterpret captured meaning.
- Existing `review_snapshot_manifest(uuid,uuid)` becomes an exact-version dispatcher in a **new migration**, preserving schema1 behavior and rejecting mixed/unknown versions. Delegates capture2 to the new helper; does not rewrite 0001.
- Existing freeze operation retains stored-pack replay first. Newly frozen capture2 emits `stewardence.review_pack.v3`; schema1 continues v2. Same expected revision, capacity reservation, control-before-capacity locks, paid receipt selection, post-wait checks and immutable SHA semantics.
- New worker envelope `stewardence.review_worker_projection.v2` admits only packv3/capture2. Old projection v1 stays packv2/snapshot1. Exact dispatcher validates full pack schema before choosing branch. Keep worker access narrow; no added capture/inventory/provider table grants.
- `build_capture_report_context(report)` in new `apps/reports/capture_context.py`, returning `AL-REPORT-CONTEXT-3`. `build_report_context` dispatches on exact input **and** result schema tuple `(1,1)` or `(2,2)` before applying legacy logic; unsupported/mixed versions fail closed. Ordinary capture2 reports must receive the same tenant/hash/admission validation, not infer issuance from valid hashes.
- `build_capture_pack_context(report_context, projection)` in new reviews module, returning `AL-REVIEW-PACK-CONTEXT-2`, with `stewardence.review_pack_render.v2`. Existing builder dispatches explicit accepted tuples; historical v2 continues permanently resolving exposure_v1.
- New `review_declared_record_v1` exposure function consumes only normalized declaration records and their provenance. Existing `historical_review_record` remains v2-only; no public alias replacement changes historical meaning.
- Renderer dispatch: exact version → closed validator → corresponding template (`capture_report.html` / `capture_review_pack.html`, or one capture template with explicit review branch). Unknown versions rejected. Historical `report.html`, keys and semantics remain unchanged. Preserve shared resource/tree/forbidden-field/size checks, escaping, network restriction and PDF canonicalization.

## Proposed capture render content

Closed reportcontext3 contains metadata, captured inventory, industry applicability, generic exposure items, qualified policy findings, evidence/unknowns, benefit model, expenditure declarations and methodology. It should omit legacy `roi`, risk histograms, highest-risk ranking and savings recommendations entirely. Explicit risk state is `not_assessed` with null score/band; benefit `not_supplied` must render as such. Known declared costs may be normalized and grouped by currency; unknown costs stay unknown and different currencies are never summed together.

Packcontext2 additionally contains frozen manifest/identity/hash, selected decision statements and exposure reviews. Original findings remain immutable. Owner completion remains `owner_statement_only=true`, `resolution_verified=false`. No completion-based conversion of an exposure item to independently verified resolution.

Do not reuse legacy recommendations or fabricate Low/0/ROI to satisfy old fields. Accounting policy applicability can be displayed without numerical risk scoring; generic non-accounting records display no qualified industry assessment.

## Authority/lifecycle to preserve

0002 `request_review_artifact` and `complete_review_pack` largely bind snapshot IDs rather than schema internals and can retain their authority protocol: same report/cycle/request/manifest hashes, exact queue payload, gate, paid/pause/lease checks after waits, reserved bytes, verified storage readback and atomic artifact/completion/queue persistence. Baseline comparison uses snapshot captured_at plus cycle ordering; keep immutable timestamps for capture2. No promotion on render/storage failure.

Decision selection currently binds Core action-card revision to snapshot result SHA. A capture2 adapter must either admit properly versioned capture2 proposals through that authority boundary or freeze an explicitly empty selection. Do not inject review questions as fabricated legacy action cards, bypass selection validation or carry completion forward. Comparison currently accepts only snapshot1 and requires a separate capture2 branch for input changes versus policy/exposure engine changes.

Report/artifact services and admission migrations also need an exact schema-guard audit: a content builder dispatch cannot override a database issuer rejecting capture2. Pure capture validation proves deterministic content, not paid authority or database issuance.

## Essential qualification

1. Existing snapshot1/packv2/context1 fixtures render identically and unsupported schema tuples fail.
2. Capture2→open→freezev3→request→actual worker projection→closed context2→real Chromium→verified private artifact→completion/baseline works under actual app/worker roles.
3. Non-accounting PDF text includes generic exposure, unknowns, not-assessed risk and benefit-not-supplied; contains no fake Low/0 score or projected savings/ROI. Accounting PDF uses only qualified policy findings and preserves unknown premises.
4. Cross-tenant/actor, missing capture issuance, mutated contracts/hashes/profile pins, mixed versions, forged decision selections and reordered/duplicated records fail before rendering or persistence.
5. Paused/expired paid/expired lease/wrong token and post-lock authority loss preserve previous baseline; storage mismatch/ambiguous write/crash cannot issue completion.
6. Closed string limits matter: capture permits 10,000-character business purpose while renderer permits 4,096 per string. Choose lossless bounded segmentation with explicit contract keys, or a visibly declared capture/render admission limit before freeze. Never silently truncate or increase old renderer limits.

Remaining integration decisions: capture issuer's exact receipt/table interface; capture2 action-card proposal issuer vs explicitly empty initial selections; capture report identifier/title; lossless long-text representation; cross-schema comparison behavior. Keep these explicit before implementation and coordinated with issuer ownership.
