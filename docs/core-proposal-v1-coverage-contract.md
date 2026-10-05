# Core proposal v1 — explicitly partial coverage

Source review date: 2026-10-04. Candidate contract clarification in response to Lyra's v4 review disposition **REVISE**. Option B is selected: retain the existing finite proposal semantics and explicitly describe their partial coverage. This document is not implementation qualification, Lyra acceptance or production approval.

The permanent implementation is `source/apps/reviews/proposals_v1.py`, contract `stewardence.core_review_proposal.v1`. Generic sources come only from `source/apps/reviews/exposure_v1.py`, contract `core.exposure.declarations.v1`, reconstructed from permanent capture v1 inputs. The five allowlisted question/outcome pairs below are exhaustive for this proposal version. There is no prose classifier, catch-all mapping or inference of a default action.

## Exhaustive generic question/state map

“None” means no proposal is generated for that state. It never means the source question is resolved, accepted, verified or absent. “Unreachable” describes permanent exposure v1's valid-input output vocabulary for that question; malformed input is rejected rather than assigned a convenient state.

| Exposure question | UNKNOWN | CONCERN | PASS | NOT_APPLICABLE |
| --- | --- | --- | --- | --- |
| `business_owner` | `exposure_unknown` / `request_declaration`: record responsible person | None: declared blank remains visible as CONCERN | None: responsible person is declared | Unreachable |
| `business_purpose` | `exposure_unknown` / `request_declaration`: record business purpose | None: declared blank remains visible as CONCERN | None: business purpose is declared | Unreachable |
| `data_categories` | None: undeclared information categories remain UNKNOWN | Unreachable | None: categories, including declared empty list, are declared | Unreachable |
| `permissions` | None: undeclared permissions remain UNKNOWN | Unreachable | None: permissions, including declared empty list, are declared | Unreachable |
| `capabilities` | None: undeclared actions remain UNKNOWN | Unreachable | None: actions, including declared empty list, are declared | Unreachable |
| `approval` | None: incomplete action/approval declarations remain UNKNOWN | `exposure_concern` / `review_declared_boundary`: review declared action and human approval boundary | None: approval requirement is declared, not enforcement-tested | None: no actions, permissions or autonomy are declared; applicability follows that declaration only |
| `account_identity` | `exposure_unknown` / `request_evidence`: provide executing account/principal evidence | Unreachable | Unreachable | Unreachable |
| `access_removal` | `exposure_unknown` / `request_evidence`: provide offboarding/access-removal evidence | Unreachable | Unreachable | Unreachable |

Account identity and access removal are always UNKNOWN in this captured inventory schema. An owner can record a later statement or evidence reference, but neither changes those original answers or becomes verified account/access evidence. Any independently admitted later contract must define its own semantics.

The permanent exposure review still displays all eight questions, including the unmapped UNKNOWN and CONCERN cases. This partial proposal collection does not replace the full Exposure Review. A capture with unknown information categories, permissions, capabilities or approval can therefore have fewer proposals than unanswered questions. No generic severity, risk score, urgency or automatic due date is assigned.

## Exhaustive qualified accounting result map

Accounting proposal eligibility is reconstructed from the complete frozen applicability object, exact permanent rule definitions/version/digest, policy engine and known-premise wrapper identities. Industry selection is customer/server capture context, not independent industry verification.

| Qualified accounting result | Proposal behavior |
| --- | --- |
| `FAIL` | `accounting_fail` / `address_qualified_failure`: copy the exact failed rule's remediation and severity, binding the complete result, rule definition, definitions set and applicability qualification digests |
| `PASS` | None; preserve the frozen rule result without converting it to verified enforcement |
| `UNKNOWN` | None; missing declared premises remain unknown and do not become failures |
| `WARNING` | None; preserve the exact rule result without a proposal; v1 maps only qualified `FAIL` |
| `NOT_APPLICABLE` | None; preserve the original qualified rule outcome |
| No qualified accounting applicability | No accounting proposals; the non-accounting capture is not assessed against this policy pack |

Every required rule premise must carry explicit declared provenance and a known value before evaluation. A false known premise does not mask another unknown premise. Neither catalog matches nor legacy storage defaults supply missing declarations. Unknown rule results do not generate a generic accounting remediation proposal.

## Immutable meaning and publication boundary

All emitted proposals retain their original outcome, `source_state_immutable=true`, `resolution_effect=none`, `authority=proposal_only` and `verification=not_established`. Decision events are owner statements with `owner_statement_only=true` and `resolution_verified=false`. Completion, evidence review, a digest, or the absence of a proposal cannot promote a source answer to verified, safe, compliant or resolved.

“All frozen proposals” in pack v4 means every proposal actually issued under this partial v1 contract is frozen, including proposals without owner statements. It does not mean every exposure UNKNOWN/CONCERN has a proposal. The full exposure questions remain visible alongside that selection. The snapshot UI must say **Selected review items and evidence requests** and disclose this finite coverage.

This clarification changes documentation and presentation only. Proposal fields, templates' semantic action/text definitions, ordering, UUID derivation, canonical hashes, SQL rule evaluation, schema identities and historical packs are unchanged. Expanding the allowlist requires a separately specified and qualified semantic successor; it must not substitute new meaning beneath v1 identities.
