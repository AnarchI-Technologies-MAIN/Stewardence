"""Pure schema-2 capture: declarations are inputs, never proof of their truth.

Every accounting premise must be known, even when another premise is false.
Unknown auxiliary vendor/retention/training facts never become legacy defaults.
SQL issuance must separately bind server identity, reviewed input and authority.
"""

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime
from uuid import UUID

import rfc8785

from .accounting_pack import ACCOUNTING_RISK_PACK_V1
from .policy_engine import ENGINE_VERSION, evaluate_rule
from .workflow_profile import validate_branch_settings

DECLARED = "Declared"
UNKNOWN = "Unknown"
INVENTORY_FACT_FIELDS = (
    "display_name",
    "vendor_name",
    "business_owner",
    "department",
    "user_count",
    "business_purpose",
    "monthly_cost_cents",
    "seat_count",
    "connected_systems",
    "data_categories",
    "permissions",
    "capabilities",
    "autonomy_level",
    "human_approval",
    "status",
)

CONTRACT = "core.capture.declarations.v1"
POLICY_CONTRACT = "core.capture.known_policy.v1"
EXPOSURE_VERSION = "core.exposure.declarations.v1"
DECLARATION_CONTRACT = "core.inventory.declarations.v1"
INDUSTRIES = frozenset(
    {"accounting_bookkeeping", "legal", "healthcare", "construction", "agency", "other"}
)
LIST_FIELDS = frozenset(
    {"connected_systems", "data_categories", "permissions", "capabilities"}
)
INT_FIELDS = frozenset(
    {"user_count", "monthly_cost_cents", "seat_count", "autonomy_level"}
)
RECORD_KEYS = frozenset(INVENTORY_FACT_FIELDS) | {
    "id",
    "product_id",
    "source_type",
    "declaration_contract",
    "declaration_as_of",
    "provenance",
    "archived_at",
}


def _canonical(value):
    return json.loads(rfc8785.dumps(value))


def _sha(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def _uuid(value):
    if type(value) is not UUID:
        raise ValueError("Typed UUID required")
    return str(value)


def _timestamp(value):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Aware capture time required")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_time(value):
    if type(value) is not str:
        raise ValueError("Declaration time required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Invalid declaration time") from error
    _timestamp(parsed)
    return parsed


def _record(record, captured_at):
    if type(record) is not dict or set(record) != RECORD_KEYS:
        raise ValueError("Exact normalized declaration record required")
    identity = record["id"]
    if type(identity) is not str or str(UUID(identity)) != identity:
        raise ValueError("Canonical inventory UUID required")
    if (
        record["declaration_contract"] != DECLARATION_CONTRACT
        or record["archived_at"] is not None
    ):
        raise ValueError("Current explicit declaration required")
    if type(record["declaration_as_of"]) is not str:
        raise ValueError("Declaration date required")
    declared_date = date.fromisoformat(record["declaration_as_of"])
    if (
        declared_date.isoformat() != record["declaration_as_of"]
        or declared_date > captured_at.astimezone(UTC).date()
    ):
        raise ValueError("Declaration cannot postdate capture")
    provenance = record["provenance"]
    if type(provenance) is not dict or set(provenance) != set(INVENTORY_FACT_FIELDS) | {
        "product_id",
        "source_type",
    }:
        raise ValueError("Exact declaration provenance required")
    if record["product_id"] is not None or provenance["product_id"] != UNKNOWN:
        raise ValueError("Capture establishes no catalog authority")
    if record["source_type"] != "manual" or provenance["source_type"] != DECLARED:
        raise ValueError("Source declaration invalid")
    for field in INVENTORY_FACT_FIELDS:
        value, basis = record[field], provenance[field]
        if basis == UNKNOWN:
            if value is not None:
                raise ValueError("Unknown declaration must be null")
        elif basis == DECLARED:
            if field in LIST_FIELDS:
                if (
                    type(value) is not list
                    or any(type(v) is not str or not v or len(v) > 200 for v in value)
                    or len(value) != len(set(value))
                ):
                    raise ValueError("Declared list invalid")
            elif field in INT_FIELDS:
                if type(value) is not int or not 0 <= value <= (
                    4 if field == "autonomy_level" else 2_147_483_647
                ):
                    raise ValueError("Declared integer invalid")
            elif field == "human_approval":
                if type(value) is not bool:
                    raise ValueError("Declared approval invalid")
            elif type(value) is not str or len(value) > (
                4096 if field == "business_purpose" else 255
            ):
                raise ValueError("Declared text invalid")
        else:
            raise ValueError("Explicit declaration basis required")
    if provenance["display_name"] != DECLARED or not record["display_name"].strip():
        raise ValueError("Reviewed tool name required")
    return _canonical(record)


def _rules():
    return _canonical([asdict(rule) for rule in ACCOUNTING_RISK_PACK_V1.rules])


def _policy_results(record):
    results = []
    for rule in ACCOUNTING_RISK_PACK_V1.rules:
        missing = sorted(
            {
                condition.field
                for condition in rule.conditions
                if record["provenance"].get(condition.field) != DECLARED
                or record.get(condition.field) is None
            }
        )
        if missing:
            result = {
                "rule_id": rule.rule_id,
                "rule_version": rule.version,
                "result": "UNKNOWN",
                "severity": None,
                "explanation": "Required declarations are not established.",
                "recommended_remediation": None,
                "effects": [],
                "missing_fields": missing,
            }
        else:
            evaluated = evaluate_rule(rule, record)
            result = {
                "rule_id": rule.rule_id,
                "rule_version": rule.version,
                "result": evaluated.result.value,
                "severity": evaluated.severity.name,
                "explanation": evaluated.explanation,
                "recommended_remediation": evaluated.recommended_remediation,
                "effects": [asdict(effect) for effect in evaluated.effects],
                "missing_fields": [],
            }
        results.append(result)
    return _canonical(results)


def build_capture_payloads(
    *,
    organization_id,
    created_by_id,
    assessment_id,
    assessment_version,
    captured_at,
    industry,
    workflow_profile_id,
    workflow_profile,
    workflow_settings,
    inventory_records,
):
    """Build deterministic payloads; caller-provided identities are not authority."""
    org, actor, assessment, profile_id = map(
        _uuid, (organization_id, created_by_id, assessment_id, workflow_profile_id)
    )
    if type(assessment_version) is not int or assessment_version != 1:
        raise ValueError("New capture assessment version must be one")
    stamp = _timestamp(captured_at)
    if type(industry) is not str or industry not in INDUSTRIES:
        raise ValueError("Supported server industry required")
    if type(workflow_profile) is not str or type(workflow_settings) is not dict:
        raise ValueError("Explicit workflow profile required")
    profile = validate_branch_settings(workflow_profile, workflow_settings)
    if type(inventory_records) is not list or not 1 <= len(inventory_records) <= 100:
        raise ValueError("Capture requires one to one hundred records")
    records = sorted(
        (_record(record, captured_at) for record in inventory_records),
        key=lambda item: UUID(item["id"]).int,
    )
    if len({record["id"] for record in records}) != len(records):
        raise ValueError("Duplicate inventory identity")
    accounting = industry == "accounting_bookkeeping"
    applicability = {
        "industry": industry,
        "policy_state": "applicable" if accounting else "not_assessed",
        "reason": "accounting_pack_selected"
        if accounting
        else "no_qualified_industry_pack",
        "generic_exposure": EXPOSURE_VERSION,
    }
    ruleset = (
        {
            "name": ACCOUNTING_RISK_PACK_V1.name,
            "version": ACCOUNTING_RISK_PACK_V1.version,
            "definitions": _rules(),
            "definitions_sha256": _sha(_rules()),
        }
        if accounting
        else None
    )
    engines = {"capture": CONTRACT, "exposure": EXPOSURE_VERSION}
    if accounting:
        engines.update(policy=ENGINE_VERSION, policy_admission=POLICY_CONTRACT)
    identity = {"id": assessment, "version": 1}
    benefit = {"state": "not_supplied"}
    inputs = {
        "snapshot_schema_version": 2,
        "capture_contract": CONTRACT,
        "assessment": identity,
        "organization_id": org,
        "created_by_id": actor,
        "captured_at": stamp,
        "industry_applicability": applicability,
        "workflow_profile": {
            "id": profile_id,
            **profile,
            "settings_sha256": _sha(profile["settings"]),
        },
        "inventory": records,
        "evidence_references": [],
        "benefit_model": benefit,
        "rulesets": {"industry": ruleset, "organization": []},
        "risk_configuration": {"state": "not_assessed"},
        "engine_versions": engines,
    }
    results = {
        "snapshot_schema_version": 2,
        "capture_contract": CONTRACT,
        "assessment": identity,
        "industry_applicability": applicability,
        "benefit_model": benefit,
        "inventory_results": [
            {
                "inventory_item_id": record["id"],
                "policy_results": _policy_results(record) if accounting else [],
                "risk": {"state": "not_assessed", "score": None, "band": None},
            }
            for record in records
        ],
    }
    inputs, results = _canonical(inputs), _canonical(results)
    return {
        "input_payload": inputs,
        "result_payload": results,
        "input_sha256": _sha(inputs),
        "result_sha256": _sha(results),
    }


def validate_capture_payloads(
    envelope, *, organization_id, created_by_id, workflow_profile_id
):
    """Recompute exact contract and pins; this does not admit database issuance."""
    if type(envelope) is not dict or set(envelope) != {
        "input_payload",
        "result_payload",
        "input_sha256",
        "result_sha256",
    }:
        raise ValueError("Exact capture envelope required")
    inputs = envelope["input_payload"]
    if type(inputs) is not dict:
        raise ValueError("Capture input required")
    try:
        expected = build_capture_payloads(
            organization_id=organization_id,
            created_by_id=created_by_id,
            workflow_profile_id=workflow_profile_id,
            assessment_id=UUID(inputs["assessment"]["id"]),
            assessment_version=inputs["assessment"]["version"],
            captured_at=_parse_time(inputs["captured_at"]),
            industry=inputs["industry_applicability"]["industry"],
            workflow_profile=inputs["workflow_profile"]["profile"],
            workflow_settings=inputs["workflow_profile"]["settings"],
            inventory_records=inputs["inventory"],
        )
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Malformed capture contract") from error
    if rfc8785.dumps(envelope) != rfc8785.dumps(expected):
        raise ValueError("Capture contract identity or content changed")
    return expected
