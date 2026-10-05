from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import rfc8785
from django.db import transaction

from apps.audit.append import append_audit_event
from apps.audit.events import EVENT_ASSESSMENT_COMPLETED
from apps.inventory.models import DetectionEvidence, InventoryItem
from apps.inventory.provenance import (
    CALCULATED,
    CATALOG_DERIVED,
    OBSERVED,
    inventory_provenance,
)
from apps.policies.context import inventory_policy_context
from apps.policies.engine import ENGINE_VERSION, PolicyResult, evaluate_policies
from apps.policies.models import OrganizationRule
from apps.policies.organization_rules import (
    compile_organization_rule,
    organization_rule_snapshot,
)
from apps.policies.packs.accounting import ACCOUNTING_RISK_PACK_V1
from apps.policies.risk import (
    DEFAULT_RISK_CONFIGURATION,
    RISK_ENGINE_VERSION,
    calculate_policy_risk,
)
from apps.roi.engine import ROI_ENGINE_VERSION, ROIInputs, calculate_roi

from .models import AssessmentSnapshot

SNAPSHOT_SCHEMA_VERSION = 1
NO_PLATFORM_RULESET = "not_published"


def canonical_bytes(value: Any) -> bytes:
    return rfc8785.dumps(value)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _canonical_payload(value: Any) -> dict[str, Any]:
    return json.loads(canonical_bytes(value))


def _decimal(value: Decimal | int) -> str:
    return str(value)


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Snapshot timestamps must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _inventory_payload(item: InventoryItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "product_id": str(item.product_id) if item.product_id else None,
        "display_name": item.display_name,
        "vendor_name": item.vendor_name,
        "business_owner": item.business_owner,
        "department": item.department,
        "user_count": item.user_count,
        "business_purpose": item.business_purpose,
        "monthly_cost_cents": item.monthly_cost_cents,
        "seat_count": item.seat_count,
        "connected_systems": list(item.connected_systems),
        "data_categories": list(item.data_categories),
        "permissions": list(item.permissions),
        "capabilities": list(item.capabilities),
        "autonomy_level": item.autonomy_level,
        "human_approval": item.human_approval,
        "status": item.status,
        "source_type": item.source_type,
        "provenance": inventory_provenance(item),
        "archived_at": _timestamp(item.archived_at) if item.archived_at else None,
    }


def _discovery_evidence_references(*, organization_id, captured_at):
    evidence = (
        DetectionEvidence.objects.select_related("scan")
        .filter(
            organization_id=organization_id,
            reconciliation_status=(DetectionEvidence.ReconciliationStatus.RECONCILED),
            inventory_item_id__isnull=False,
            scan__received_at__lte=captured_at,
        )
        .order_by("inventory_item_id", "-scan__received_at", "-id")
    )
    latest_by_inventory = {}
    for observation in evidence:
        latest_by_inventory.setdefault(observation.inventory_item_id, observation)
    return tuple(
        {
            "type": "collector_observation",
            "reference": observation.evidence_hash,
            "provenance": OBSERVED,
            "evidence_id": str(observation.id),
            "scan_id": str(observation.scan_id),
            "scan_hash": observation.scan.scan_hash,
            "coverage": observation.scan.bundle["coverage"].get(
                observation.record["detector_id"]
            ),
            "detector_id": observation.record["detector_id"],
            "detector_version": observation.record["detector_version"],
            "observed_at": observation.record["observed_at"],
            "evidence_type": observation.record["evidence_type"],
            "evidence_locator": observation.record["evidence_locator"],
            "raw_identifier": observation.record["raw_identifier"],
            "reported_version": observation.record["version"],
            "reported_publisher": observation.record["publisher"],
            "reconciliation_status": observation.reconciliation_status,
            "reconciliation_reason": observation.reconciliation_reason,
            "reconciliation_provenance": CATALOG_DERIVED,
            "matched_product_id": str(observation.matched_product_id),
            "inventory_item_id": str(observation.inventory_item_id),
        }
        for observation in sorted(
            latest_by_inventory.values(), key=lambda item: str(item.inventory_item_id)
        )
    )


def _roi_inputs_payload(inputs: ROIInputs) -> dict[str, Any]:
    return {
        name: {
            "value": _decimal(assumption.value),
            "provenance": assumption.provenance.value,
        }
        for name, assumption in (
            ("monthly_subscription_cost", inputs.monthly_subscription_cost),
            ("implementation_cost", inputs.implementation_cost),
            (
                "implementation_amortization_months",
                inputs.implementation_amortization_months,
            ),
            ("hours_saved_per_month", inputs.hours_saved_per_month),
            ("loaded_hourly_rate", inputs.loaded_hourly_rate),
            ("attributable_revenue", inputs.attributable_revenue),
            ("avoided_monthly_cost", inputs.avoided_monthly_cost),
        )
    }


def _policy_result_payload(result) -> dict[str, Any]:
    return {
        "rule_id": result.rule_id,
        "rule_version": result.rule_version,
        "evidence": [
            {"field": field, "value": value} for field, value in result.evidence
        ],
        "result": result.result.value,
        "explanation": result.explanation,
        "severity": result.severity.name,
        "recommended_remediation": result.recommended_remediation,
        "effects": [
            {
                "type": effect.type,
                "dimension": effect.dimension,
                "value": effect.value,
                "control": effect.control,
                "message": effect.message,
            }
            for effect in result.effects
        ],
    }


def _risk_result_payload(risk) -> dict[str, Any]:
    return {
        "provenance": CALCULATED,
        "engine_version": risk.engine_version,
        "configuration_version": risk.configuration_version,
        "score": risk.score,
        "band": risk.band.value,
        "severity_floor": (risk.severity_floor.value if risk.severity_floor else None),
        "raw_weighted_score": _decimal(risk.raw_weighted_score),
        "dimensions": [
            {
                "dimension": item.dimension.value,
                "raw_points": item.raw_points,
                "score": item.score,
                "weight_percent": item.weight_percent,
                "weighted_points": _decimal(item.weighted_points),
            }
            for item in risk.dimensions
        ],
        "contributions": [
            {
                "reason": item.reason,
                "rule_id": item.rule_id,
                "rule_version": item.rule_version,
                "dimension": item.dimension.value,
                "points": item.points,
            }
            for item in risk.contributions
        ],
    }


def _roi_result_payload(result) -> dict[str, Any]:
    return {
        "provenance": CALCULATED,
        "engine_version": result.engine_version,
        "monthly_labor_value": _decimal(result.monthly_labor_value),
        "monthly_value": _decimal(result.monthly_value),
        "amortized_implementation_cost": _decimal(result.amortized_implementation_cost),
        "monthly_total_cost": _decimal(result.monthly_total_cost),
        "monthly_net_value": _decimal(result.monthly_net_value),
        "roi_percent": (
            _decimal(result.roi_percent) if result.roi_percent is not None else None
        ),
        "arithmetic": list(result.arithmetic),
    }


def verify_snapshot(snapshot: AssessmentSnapshot) -> bool:
    return (
        canonical_sha256(snapshot.input_payload) == snapshot.input_sha256
        and canonical_sha256(snapshot.result_payload) == snapshot.result_sha256
    )


@transaction.atomic
def create_assessment_snapshot(
    *,
    organization_id,
    created_by_id,
    assessed_item_id,
    roi_inputs: ROIInputs,
    captured_at: datetime,
    evidence_references: tuple[dict[str, Any], ...] = (),
    previous_snapshot: AssessmentSnapshot | None = None,
) -> AssessmentSnapshot:
    if previous_snapshot is not None:
        stored_previous = (
            AssessmentSnapshot.objects.select_for_update()
            .filter(pk=previous_snapshot.pk)
            .first()
        )
        if (
            stored_previous is None
            or stored_previous.organization_id != organization_id
        ):
            raise ValueError("A snapshot revision must remain in the same organization")
        if not verify_snapshot(stored_previous):
            raise ValueError("A snapshot revision requires valid prior hashes")
        latest_version = (
            AssessmentSnapshot.objects.filter(
                organization_id=organization_id,
                assessment_id=stored_previous.assessment_id,
            )
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        if latest_version != stored_previous.version:
            raise ValueError("A snapshot revision must extend the latest version")
        previous_snapshot = stored_previous
    assessment_id = (
        previous_snapshot.assessment_id if previous_snapshot else uuid.uuid4()
    )
    version = previous_snapshot.version + 1 if previous_snapshot else 1
    captured_timestamp = _timestamp(captured_at)
    inventory = tuple(
        InventoryItem.objects.select_related("product__vendor")
        .filter(organization_id=organization_id)
        .order_by("id")
    )
    if not any(item.id == assessed_item_id for item in inventory):
        raise ValueError("The ROI item must belong to the snapshotted inventory")
    organization_rule_records = tuple(
        OrganizationRule.objects.filter(
            organization_id=organization_id,
            enabled=True,
        ).order_by("id")
    )
    organization_rules = tuple(
        compile_organization_rule(record) for record in organization_rule_records
    )
    captured_evidence = tuple(evidence_references) + _discovery_evidence_references(
        organization_id=organization_id,
        captured_at=captured_at,
    )

    input_payload = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "assessment": {"id": str(assessment_id), "version": version},
        "organization_id": str(organization_id),
        "captured_at": captured_timestamp,
        "inventory": [_inventory_payload(item) for item in inventory],
        "evidence_references": list(captured_evidence),
        "rulesets": {
            "platform": NO_PLATFORM_RULESET,
            "industry": {
                "name": ACCOUNTING_RISK_PACK_V1.name,
                "version": ACCOUNTING_RISK_PACK_V1.version,
            },
            "organization": [
                organization_rule_snapshot(record)
                for record in organization_rule_records
            ],
        },
        "risk_configuration": {
            "version": DEFAULT_RISK_CONFIGURATION.version,
            "weights": [
                {"dimension": dimension.value, "percent": weight}
                for dimension, weight in DEFAULT_RISK_CONFIGURATION.weights
            ],
        },
        "roi": {
            "assessed_item_id": str(assessed_item_id),
            "assumptions": _roi_inputs_payload(roi_inputs),
        },
        "engine_versions": {
            "policy": ENGINE_VERSION,
            "risk": RISK_ENGINE_VERSION,
            "roi": ROI_ENGINE_VERSION,
        },
    }

    inventory_results = []
    for item in inventory:
        policy = evaluate_policies(
            ACCOUNTING_RISK_PACK_V1.rules + organization_rules,
            inventory_policy_context(item),
        )
        risk = calculate_policy_risk(policy)
        inventory_results.append(
            {
                "inventory_item_id": str(item.id),
                "policy_results": [
                    _policy_result_payload(result)
                    for result in policy.results
                    if result.result is not PolicyResult.NOT_APPLICABLE
                ],
                "risk": _risk_result_payload(risk),
            }
        )

    result_payload = {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "assessment": {"id": str(assessment_id), "version": version},
        "inventory_results": inventory_results,
        "roi": _roi_result_payload(calculate_roi(roi_inputs)),
    }
    input_payload = _canonical_payload(input_payload)
    result_payload = _canonical_payload(result_payload)
    snapshot = AssessmentSnapshot.objects.create(
        organization_id=organization_id,
        assessment_id=assessment_id,
        version=version,
        created_by_id=created_by_id,
        captured_at=captured_at,
        input_payload=input_payload,
        result_payload=result_payload,
        input_sha256=canonical_sha256(input_payload),
        result_sha256=canonical_sha256(result_payload),
    )
    append_audit_event(
        organization_id=organization_id,
        actor_user_id=created_by_id,
        event_type=EVENT_ASSESSMENT_COMPLETED,
        entity_type="assessment_snapshot",
        entity_id=snapshot.id,
        data={
            "assessment_id": str(snapshot.assessment_id),
            "input_sha256": snapshot.input_sha256,
            "result_sha256": snapshot.result_sha256,
            "version": str(snapshot.version),
        },
    )
    return snapshot
