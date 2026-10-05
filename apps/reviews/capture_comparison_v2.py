"""Permanent declaration comparison; admission and causal attribution are separate."""

from copy import deepcopy
from uuid import UUID

from apps.assessments.capture_v1 import validate_capture_payloads
from apps.assessments.snapshots import canonical_sha256, verify_snapshot

from .exposure_v1 import review_record

VERSION = "core.snapshot_comparison.v2"


def compare_captures(*, baseline, current, organization_id):
    if type(organization_id) is not UUID:
        raise ValueError("Typed organization identity required")
    for snapshot in (baseline, current):
        if snapshot.organization_id != organization_id or not verify_snapshot(snapshot):
            raise ValueError("Intact same-organization captures required")
        validate_capture_payloads(
            {
                "input_payload": snapshot.input_payload,
                "result_payload": snapshot.result_payload,
                "input_sha256": snapshot.input_sha256,
                "result_sha256": snapshot.result_sha256,
            },
            organization_id=organization_id,
            created_by_id=snapshot.created_by_id,
            workflow_profile_id=UUID(snapshot.input_payload["workflow_profile"]["id"]),
        )
    if baseline.captured_at > current.captured_at:
        raise ValueError("Comparison baseline is newer than the current snapshot")
    if baseline.id == current.id and (
        baseline.input_sha256 != current.input_sha256
        or baseline.result_sha256 != current.result_sha256
    ):
        raise ValueError("One snapshot identity cannot name different content")
    inputs = [snapshot.input_payload for snapshot in (baseline, current)]
    records = [{row["id"]: row for row in payload["inventory"]} for payload in inputs]
    changes = []
    exposures = []
    policies = []
    policy_rows = [
        {
            row["inventory_item_id"]: row["policy_results"]
            for row in snapshot.result_payload["inventory_results"]
        }
        for snapshot in (baseline, current)
    ]
    for identity in sorted(records[0].keys() | records[1].keys()):
        before, after = (indexed.get(identity) for indexed in records)
        if before != after:
            fields = []
            vocabulary = (before or after)["provenance"]
            for field in sorted(vocabulary):
                previous = (
                    {
                        "value": before.get(field),
                        "provenance": before["provenance"][field],
                    }
                    if before is not None
                    else None
                )
                following = (
                    {
                        "value": after.get(field),
                        "provenance": after["provenance"][field],
                    }
                    if after is not None
                    else None
                )
                if previous != following:
                    fields.append(
                        {"field": field, "before": previous, "after": following}
                    )
            changes.append(
                {
                    "inventory_item_id": identity,
                    "change": "added"
                    if before is None
                    else "removed"
                    if after is None
                    else "changed",
                    "field_changes": fields,
                    "declaration_as_of_changed": (before or {}).get("declaration_as_of")
                    != (after or {}).get("declaration_as_of"),
                    "before_sha256": canonical_sha256(before)
                    if before is not None
                    else None,
                    "after_sha256": canonical_sha256(after)
                    if after is not None
                    else None,
                }
            )
        previous_review = review_record(before) if before is not None else None
        current_review = review_record(after) if after is not None else None
        if previous_review != current_review:
            exposures.append(
                {
                    "inventory_item_id": identity,
                    "before": previous_review,
                    "after": current_review,
                }
            )
        previous_policy, current_policy = (
            indexed.get(identity) for indexed in policy_rows
        )
        if previous_policy != current_policy:
            policies.append(
                {
                    "inventory_item_id": identity,
                    "before": previous_policy,
                    "after": current_policy,
                }
            )
    result = {
        "schema": VERSION,
        "organization_id": str(organization_id),
        "baseline_snapshot_id": str(baseline.id),
        "current_snapshot_id": str(current.id),
        "baseline_input_sha256": baseline.input_sha256,
        "baseline_result_sha256": baseline.result_sha256,
        "current_input_sha256": current.input_sha256,
        "current_result_sha256": current.result_sha256,
        "declaration_changes": changes,
        "exposure_changes": exposures,
        "policy_result_changes": policies,
        "configuration_changes": [
            field
            for field in (
                "industry_applicability",
                "rulesets",
                "risk_configuration",
                "engine_versions",
                "workflow_profile",
            )
            if inputs[0][field] != inputs[1][field]
        ],
        "attribution": "not_established",
        "completion_carry_forward": False,
        "baseline_promotion": False,
        "risk_assessed": False,
        "benefit_model": "not_supplied",
    }
    return deepcopy({**result, "sha256": canonical_sha256(result)})
