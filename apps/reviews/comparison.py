"""Pure comparison of caller-admitted immutable assessment snapshots.

This function proves content integrity, not tenant admission or input truth.
Callers must select the baseline through the qualified owner/tenant boundary.
It issues no decisions and never carries a completion into a changed finding.
"""

from uuid import UUID

from apps.assessments.snapshots import canonical_sha256, verify_snapshot

VERSION = "core.snapshot_comparison.v1"


def _index(records, field):
    if type(records) is not list:
        raise ValueError("Snapshot records must be an array")
    indexed = {}
    for record in records:
        if type(record) is not dict or field not in record:
            raise ValueError("Snapshot record identity is missing")
        if type(record[field]) is not str:
            raise ValueError("Snapshot record identity must be UUID text")
        identity = str(UUID(record[field]))
        if identity in indexed:
            raise ValueError("Snapshot record identities must be unique")
        indexed[identity] = record
    return indexed


def _changes(before, after):
    changes = []
    for identity in sorted(before.keys() | after.keys()):
        previous, current = before.get(identity), after.get(identity)
        if previous == current:
            continue
        fields = sorted(
            key
            for key in (previous or {}).keys() | (current or {}).keys()
            if key not in (previous or {})
            or key not in (current or {})
            or previous[key] != current[key]
        )
        changes.append(
            {
                "inventory_item_id": identity,
                "change": "added"
                if previous is None
                else "removed"
                if current is None
                else "changed",
                "fields": fields,
                "before_sha256": canonical_sha256(previous)
                if previous is not None
                else None,
                "after_sha256": canonical_sha256(current)
                if current is not None
                else None,
            }
        )
    return changes


def _compare_schema1(*, baseline, current, organization_id):
    """Return reproducible change evidence; baseline authority is caller-owned."""
    if not isinstance(organization_id, UUID):
        raise ValueError("Typed organization identity required")
    for snapshot in (baseline, current):
        if snapshot.organization_id != organization_id:
            raise ValueError("Cross-organization comparison denied")
        if (
            type(snapshot.input_payload) is not dict
            or type(snapshot.result_payload) is not dict
        ):
            raise ValueError("Snapshot payloads must be objects")
        if not verify_snapshot(snapshot):
            raise ValueError("Snapshot content integrity failed")
        if snapshot.input_payload.get("organization_id") != str(organization_id):
            raise ValueError("Snapshot payload organization mismatch")
        if (
            type(snapshot.input_payload.get("snapshot_schema_version")) is not int
            or type(snapshot.result_payload.get("snapshot_schema_version")) is not int
            or snapshot.input_payload.get("snapshot_schema_version") != 1
            or snapshot.result_payload.get("snapshot_schema_version") != 1
        ):
            raise ValueError("Unsupported comparison snapshot schema")
    if baseline.captured_at > current.captured_at:
        raise ValueError("Comparison baseline is newer than the current snapshot")
    if baseline.id == current.id and (
        baseline.input_sha256 != current.input_sha256
        or baseline.result_sha256 != current.result_sha256
    ):
        raise ValueError("One snapshot identity cannot name different content")

    inputs_before, inputs_after = baseline.input_payload, current.input_payload
    inventory = _changes(
        _index(inputs_before.get("inventory"), "id"),
        _index(inputs_after.get("inventory"), "id"),
    )
    findings = _changes(
        _index(baseline.result_payload.get("inventory_results"), "inventory_item_id"),
        _index(current.result_payload.get("inventory_results"), "inventory_item_id"),
    )
    configuration_changes = [
        field
        for field in ("rulesets", "risk_configuration", "engine_versions")
        if inputs_before.get(field) != inputs_after.get(field)
    ]
    review = {
        "schema": VERSION,
        "organization_id": str(organization_id),
        "baseline_snapshot_id": str(baseline.id),
        "current_snapshot_id": str(current.id),
        "baseline_input_sha256": baseline.input_sha256,
        "baseline_result_sha256": baseline.result_sha256,
        "current_input_sha256": current.input_sha256,
        "current_result_sha256": current.result_sha256,
        "inventory_changes": inventory,
        "finding_changes": findings,
        "configuration_changes": configuration_changes,
        "evidence_references_changed": inputs_before.get("evidence_references")
        != inputs_after.get("evidence_references"),
        "roi_inputs_changed": inputs_before.get("roi") != inputs_after.get("roi"),
        "attribution": "not_established",
        "completion_carry_forward": False,
    }
    return {**review, "sha256": canonical_sha256(review)}


def compare_snapshots(*, baseline, current, organization_id):
    """Explicit version dispatch; mixed generations remain inadmissible."""
    schemas = [
        snapshot.input_payload.get("snapshot_schema_version")
        if type(snapshot.input_payload) is dict
        else None
        for snapshot in (baseline, current)
    ]
    if all(type(schema) is int and schema == 2 for schema in schemas):
        from .capture_comparison_v2 import compare_captures

        return compare_captures(
            baseline=baseline, current=current, organization_id=organization_id
        )
    return _compare_schema1(
        baseline=baseline, current=current, organization_id=organization_id
    )
