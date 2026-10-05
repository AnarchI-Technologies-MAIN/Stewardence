# Capture historical semantics and proposed pack v4

Read-only audit during the frozen integrated qualification. No product, migration, gate, provider, or qualification changes. Consultation evidence: `evidence/lyra-exposure-proposal-design-disposition-20261004.txt` approves **implementation planning with narrow revisions**, explicitly not production.

## Current behavior and future drift

Current capture2 input/result hashes, capture issuance receipt and review manifest pin immutable content. Packv3 freezes an empty selection; worker projectionv2 and context `AL-REVIEW-PACK-CONTEXT-2` preserve this boundary. Historical packv2 dispatches explicitly to permanent `exposure_v1`; capturev3 context also imports that implementation directly. No changed output or executed historical corruption was established in this audit.

The remaining dependency risk is real in source: `capture_context.validate_capture_projection` calls `capture_contract.validate_capture_payloads`, which rebuilds the full envelope with today's dependencies. A future otherwise valid change can therefore reject an authentic historical pack. Hashes detect changed content; they do not choose the historical implementation required to interpret it.

| Dependency in capture_contract | Future change under the same contract | Historical consequence |
|---|---|---|
| Current `INVENTORY_FACT_FIELDS`, DECLARED/UNKNOWN constants | Add/rename a fact or change provenance vocabulary | Exact record/provenance sets reject old records, including non-accounting captures |
| Current `validate_branch_settings` | Change accepted keys, normalization, bounds or profiles | Rebuilding old frozen profile settings fails or differs despite the stored settings hash |
| Current `ACCOUNTING_RISK_PACK_V1` object | Edit rule conditions, ordering, explanation, severity or remediation in place | Frozen definitions or recomputed results differ; old accounting capture validation fails |
| Current `ENGINE_VERSION`, `evaluate_rule` and rule dataclasses | Bump the engine alias, change enum representation/evaluation or serialized dataclass fields | Reconstructed engine versions, definitions or result payload changes |
| Capture module's own constants/algorithms | Change date normalization, count/string bounds, applicability, unknown-premise rules or benefit/risk shape without successor version | Same-version historical content rejects or new captures acquire different meanings |
| rfc8785/JSON/library behavior | Change canonical serialization or unsupported-type handling | Canonical hash/serialization disagreement; requires explicit compatibility qualification |

The worker's strict recomputation generally turns this into a **fail-closed availability/reproducibility risk**, not automatic acceptance of a falsified old hash. Changing an evaluator while leaving its version string unchanged additionally makes newly issued content share a name with incompatible semantics. Neither outcome is acceptable historical versioning.

The standalone renderer's capture validator deliberately has no application imports. Its record fields, exposure outcomes and limits are embedded in the renderer contract. A future edit there under context2 could likewise reject or reinterpret an old request. SQL 0004 embeds exact capture/profile/receipt versions and derives historical function bodies from predecessor migrations; editing an old migration or its source-generation assumptions would affect fresh reconstruction. Existing installed database bodies are not automatically changed by a Python alias edit. Keep source reconstruction and installed runtime distinctions explicit.

## Minimal permanent dispatch plan

1. Preserve the current capture contract byte/semantic behavior in a permanent `capture_declarations_v1` implementation. Pin its provenance field tuple/constants, workflow validator, accounting definitions and evaluator semantics. A file named v1 is insufficient if it still imports mutable current aliases.
2. Preserve the evaluator and rule definitions needed for `core.capture.known_policy.v1` behind permanent modules or immutable qualified serialized definitions plus a permanent evaluator. Keep the current source-verified accounting pack distinct from new industry packs. Record golden hashes for full definitions and representative results.
3. Make `capture_contract.py` an exact dispatcher keyed by the frozen input/result capture contract and engine tuple. New issuance can select a successor contract; historical validation selects the old permanent implementation. Reject mixed input/result versions and unknown tuples. Do not dispatch by current organization industry/profile or a latest alias.
4. Preserve current `capture_context` and renderer context2 semantics as permanent historical branches. Future context versions use separate validators/templates; no v3 manifest gains decisions, baseline meaning, inferred severity or a different exposure implementation. Packv2 remains on its original permanent exposure path.
5. Use additive migrations to install successor dispatch/issuers. Keep old migrations, immutable rows, canonical hashes, receipt identities, request/lease/control authority and private report policies unchanged. Do not backfill new proposal selections into an old manifest.

Moving current implementation behind permanent modules needs differential qualification: same fixtures and representative admitted rows produce identical canonical payloads, hashes, decisions/exposure and rendered semantic text. This audit proposes that refactor; it does not assert it has happened.

## Proposed v4 proposal-to-render boundary

Proposed names: `stewardence.review_pack.v4`, `core.review_proposals.v1`, `stewardence.core_review_proposal.v1`, worker projectionv3 and `AL-REVIEW-PACK-CONTEXT-3`. These are design names pending coordinated closed schemas, not shipped APIs.

Every proposal has an immutable issuer identity and canonical payload digest. Keep a separately defined semantic idempotency key that excludes issuer UUID/time; avoid digest self-reference. Concurrency must yield one admitted revision for the same exact semantic request. A digest or deterministic UUID does not prove issuance.

Required source bindings:

- Generic: snapshot ID/result SHA, inventory item ID/record SHA, permanent exposure contract, question ID/outcome/source-fields and **digest of the entire exact question**, including explanation/basis/verification.
- Accounting: the same snapshot/record pins, exact qualified applicability contract/version/qualification digest, rule identity/version/definitions digest and full frozen FAIL-result digest. The issuer cannot apply today's industry/profile interpretation to an old capture. Existing capture2's industry marker alone is not a new qualification receipt; a v4 proposal admission must explicitly bind the qualified basis without mutating the capture.
- Source class is `exposure_unknown`, `exposure_concern` or `accounting_fail`. Closed action kinds distinguish request_declaration, request_evidence, review_declared_boundary and address_qualified_failure. Unknown evidence gaps do not become qualified failures. Generic proposals have no severity/risk score, automatic due date or inferred urgency.

The narrow proposal issuer recomputes permanent semantics from frozen records and verifies exact source bindings; accepts a request to generate proposals, never client-authored proposal text/outcomes/authority. Lock/recheck owner, tenant, paid and work authority after waits. App raw insertion and worker issuance remain denied. If PostgreSQL does not independently recompute the Python engine, document the exact separately trusted issuance boundary instead of claiming that caller-computable digests prove engine execution.

Manifestv4 freezes `proposal_contract_version`, selected proposal identities/digests/source class/source identity/source digest, and selected decision identities/digests. Each decision binds one exact selected proposal `(proposal_id, proposal_sha256)`. Existing legacy revision/card-index fields, if retained for an explicit bridge, are additional validated source pins—not a substitute for the proposal identity. Replay uses the recorded selection, not latest proposals or latest events.

Projectionv3 resolves each selected identity through the narrow lease-scoped boundary. It supplies the immutable proposal payload and its source question/rule evidence plus the exact selected decision payload. Closed context3 and renderer independently check one-to-one references, canonical hashes, duplicate/missing/foreign selections, source-class/action consistency and known semantic versions. No current aliases, live inventory, provider permission queries or prose parsing choose authority.

Owner events retain `owner_statement_only=true`, `resolution_verified=false`; original source state remains immutable and resolution_effect is none. Completion/evidence_reviewed means the owner reported a step. A later capture may independently record new declarations and produce a new result. It does not erase old UNKNOWN or transfer an old completion automatically. The renderer visibly separates evidence gaps, declared concerns, qualified failures and later owner statements.

## Required tests before a successor slice qualifies

- Golden v1 capture/packv2/v3 fixtures continue identical after current provenance, workflow, accounting-pack and engine aliases are monkeypatched to successors; historical dispatch must not touch them. Changing actual permanent definitions must fail golden checks.
- Engine-only updates and record-only updates remain distinguishable; old stored inputs/results/manifests are never rewritten. Mixed/unknown versions reject; standalone renderer image works without apps imports.
- UNKNOWN creates only the specified evidence/declaration request; CONCERN creates a declared-boundary review; PASS/N/A create no proposal. Preserve exposure_v1's original scope, including account/offboarding remaining unknown in that schema.
- Qualified accounting FAIL emits only under exact frozen qualified applicability; non-accounting/UNKNOWN premises do not emit accounting failure proposals. Generic source classes never acquire numerical severity/risk.
- Rehashed altered source question/explanation/fields/outcome, record, applicability, rule result or snapshot digest rejects at issuance and selected-identity projection. Client metadata cannot create source authority.
- Duplicate proposal IDs, same ID with different SHA, missing selected proposal, unrelated decision, cross-tenant actor/selection and latest-event substitution reject. Actual-role raw app insertion and worker issuance deny; concurrent requests issue one canonical revision.
- Owner completion/evidence_reviewed never changes source UNKNOWN or sets verified/resolved/safe/compliant. New capture creates independent results and linked fresh proposals rather than completion carryforward.
- Frozen v4 replays identical selected payloads after live inventory, proposal generation and decision events change. Paid/pause/lease post-wait checks, storage readback, atomic completion/rollback and private access remain required, with actual worker/Chromium qualification separate from pure mapping tests.

Production approval remains open. This document adds a historical compatibility gate and successor identity map; it does not authorize implementation, provider writes, deployment or enabling gates.
