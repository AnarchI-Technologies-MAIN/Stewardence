"""Permanent, explicitly partial v1 proposal coverage.

Only five generic question/outcome pairs emit proposals; other UNKNOWN or
CONCERN answers remain visible in the full Exposure Review without a card.
Qualified accounting FAIL results are separately mapped. See
docs/core-proposal-v1-coverage-contract.md for the exhaustive state map.
Reproducibility is neither issuance nor input truth. Expanded coverage needs
a semantic successor, never an in-place replacement of these v1 identities.
"""

import hashlib
import json
from uuid import UUID, uuid5

import rfc8785

from .capture import validate_capture_payloads
from .exposure import VERSION as EXPOSURE_VERSION
from .exposure import review_record

VERSION = "stewardence.core_review_proposal.v1"
APPLICABILITY_VERSION = "stewardence.core_review_proposal_applicability.v1"
NAMESPACE = UUID("0b59c53e-e126-56e6-b67c-c0d5041355c2")

# A finite semantic vocabulary, never prose classification or a mutable alias.
_TEMPLATES = (
    (
        "business_owner",
        "UNKNOWN",
        "request_declaration",
        "Record the responsible person as an owner declaration.",
    ),
    (
        "business_purpose",
        "UNKNOWN",
        "request_declaration",
        "Record the business purpose as an owner declaration.",
    ),
    (
        "account_identity",
        "UNKNOWN",
        "request_evidence",
        "Provide executing account or principal evidence for owner review.",
    ),
    (
        "access_removal",
        "UNKNOWN",
        "request_evidence",
        "Provide access-removal or offboarding evidence for owner review.",
    ),
    (
        "approval",
        "CONCERN",
        "review_declared_boundary",
        "Review the declared action and human approval boundary.",
    ),
)


def _sha(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _copy(value):
    return json.loads(rfc8785.dumps(value))


def build_review_proposals(*, snapshot_id, capture_envelope):
    """Recompute from exact capture v2; database admission remains separate."""
    if type(snapshot_id) is not UUID:
        raise ValueError("Exact snapshot UUID required")
    try:
        inputs = capture_envelope["input_payload"]
        value = validate_capture_payloads(
            capture_envelope,
            organization_id=UUID(inputs["organization_id"]),
            created_by_id=UUID(inputs["created_by_id"]),
            workflow_profile_id=UUID(inputs["workflow_profile"]["id"]),
        )
    except (KeyError, TypeError, AttributeError, ValueError) as error:
        raise ValueError("Exact permanent capture v2 required") from error
    inputs, results = value["input_payload"], value["result_payload"]
    if inputs["assessment"]["id"] != str(snapshot_id):
        raise ValueError("Snapshot identity mismatch")
    qualification = {
        "schema": APPLICABILITY_VERSION,
        "industry_applicability": inputs["industry_applicability"],
        "ruleset": inputs["rulesets"]["industry"],
        "engine_versions": inputs["engine_versions"],
    }
    qualification_sha = _sha(qualification)
    rows = {row["inventory_item_id"]: row for row in results["inventory_results"]}
    proposals = []

    def emit(record, source, action, text, severity=None):
        identity = str(
            uuid5(
                NAMESPACE,
                rfc8785.dumps(
                    {
                        "snapshot_id": str(snapshot_id),
                        "contract": VERSION,
                        "inventory_item_id": record["id"],
                        "source_class": source["class"],
                        "source_identity": source["identity"],
                        "source_digest": source["digest"],
                    }
                ).decode(),
            )
        )
        payload = {
            "schema": VERSION,
            "proposal_id": identity,
            "organization_id": inputs["organization_id"],
            "snapshot_id": str(snapshot_id),
            "snapshot_input_sha256": value["input_sha256"],
            "snapshot_result_sha256": value["result_sha256"],
            "inventory_item_id": record["id"],
            "record_sha256": _sha(record),
            "source": source,
            "action_kind": action,
            "proposal_text": text,
            "authority": "proposal_only",
            "verification": "not_established",
            "original_outcome": source["outcome"],
            "source_state_immutable": True,
            "resolution_effect": "none",
            "owner_statement_only": True,
            "resolution_verified": False,
        }
        if severity is not None:
            payload["severity"] = severity
        proposals.append({**payload, "sha256": _sha(payload)})

    for record in inputs["inventory"]:
        review = _copy(review_record(record))
        for question in review["questions"]:
            for question_id, outcome, action, text in _TEMPLATES:
                if (question["question_id"], question["outcome"]) != (
                    question_id,
                    outcome,
                ):
                    continue
                definition = {
                    "exposure_contract": EXPOSURE_VERSION,
                    "question_id": question_id,
                    "outcome": outcome,
                    "action_kind": action,
                    "proposal_text": text,
                }
                emit(
                    record,
                    {
                        "class": "exposure_unknown"
                        if outcome == "UNKNOWN"
                        else "exposure_concern",
                        "contract": EXPOSURE_VERSION,
                        "contract_version": 1,
                        "identity": question_id,
                        "digest": _sha(question),
                        "definition_sha256": _sha(definition),
                        "outcome": outcome,
                        "source_fields": question["source_fields"],
                    },
                    action,
                    text,
                )
        if inputs["industry_applicability"]["policy_state"] != "applicable":
            continue
        ruleset = inputs["rulesets"]["industry"]
        definitions = {rule["rule_id"]: rule for rule in ruleset["definitions"]}
        for result in rows[record["id"]]["policy_results"]:
            if result["result"] != "FAIL":
                continue
            rule = definitions[result["rule_id"]]
            emit(
                record,
                {
                    "class": "accounting_fail",
                    "contract": ruleset["name"],
                    "contract_version": ruleset["version"],
                    "identity": result["rule_id"],
                    "rule_version": result["rule_version"],
                    "digest": _sha(result),
                    "definition_sha256": _sha(rule),
                    "definitions_sha256": ruleset["definitions_sha256"],
                    "outcome": "FAIL",
                    "source_fields": sorted(
                        {condition["field"] for condition in rule["conditions"]}
                    ),
                    "applicability_contract": APPLICABILITY_VERSION,
                    "applicability_sha256": _sha(inputs["industry_applicability"]),
                    "qualification_sha256": qualification_sha,
                    "policy_engine": inputs["engine_versions"]["policy"],
                    "policy_admission": inputs["engine_versions"]["policy_admission"],
                },
                "address_qualified_failure",
                result["recommended_remediation"],
                result["severity"],
            )
    return _copy(
        sorted(
            proposals,
            key=lambda proposal: (
                proposal["inventory_item_id"],
                proposal["source"]["class"],
                proposal["source"]["identity"],
                proposal["proposal_id"],
            ),
        )
    )


def validate_review_proposals(*, snapshot_id, capture_envelope, proposals):
    """Exact closed recomputation; a correct caller digest never proves issuance."""
    expected = build_review_proposals(
        snapshot_id=snapshot_id, capture_envelope=capture_envelope
    )
    if type(proposals) is not list:
        raise ValueError("Exact proposal list required")
    try:
        if rfc8785.dumps(proposals) != rfc8785.dumps(expected):
            raise ValueError("Proposal semantics or identities mismatch")
    except (TypeError, rfc8785.CanonicalizationError) as error:
        raise ValueError("Canonical proposal list required") from error
    return _copy(expected)
