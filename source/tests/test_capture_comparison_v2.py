"""Pure declaration changes are not admission, causal attribution or remediation."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from apps.assessments.capture_v1 import build_capture_payloads
from apps.assessments.snapshots import canonical_sha256
from apps.reviews.capture_comparison_v2 import compare_captures
from tests.test_capture_contract import args, record


def pair():
    item = record(UUID(int=5))
    pins = args("other", [item])
    snapshots = []
    for index in range(2):
        if index:
            item["business_owner"] = "Owner"
            item["provenance"]["business_owner"] = "Declared"
            pins["assessment_id"] = uuid4()
            pins["captured_at"] += timedelta(hours=1)
        envelope = build_capture_payloads(**pins)
        snapshots.append(
            SimpleNamespace(
                id=pins["assessment_id"],
                organization_id=pins["organization_id"],
                created_by_id=pins["created_by_id"],
                captured_at=pins["captured_at"],
                **envelope,
            )
        )
    return snapshots


def compare(snapshots, org=None):
    return compare_captures(
        baseline=snapshots[0],
        current=snapshots[1],
        organization_id=org or snapshots[0].organization_id,
    )


def test_unknown_to_declaration_has_exact_values_and_no_resolution():
    snapshots = pair()
    result = compare(snapshots)
    assert result["declaration_changes"][0]["field_changes"] == [
        {
            "field": "business_owner",
            "before": {"value": None, "provenance": "Unknown"},
            "after": {"value": "Owner", "provenance": "Declared"},
        }
    ]
    assert (
        result["exposure_changes"][0]["before"]["questions"][0]["outcome"] == "UNKNOWN"
    )
    assert result["exposure_changes"][0]["after"]["questions"][0]["outcome"] == "PASS"
    assert not result["completion_carry_forward"] and not result["baseline_promotion"]
    assert not result["risk_assessed"]
    assert result["attribution"] == "not_established"
    assert result["benefit_model"] == "not_supplied"
    assert not result["policy_result_changes"]
    assert result == compare(snapshots)
    result["declaration_changes"][0]["field_changes"][0]["after"]["value"] = "Altered"
    assert snapshots[1].input_payload["inventory"][0]["business_owner"] == "Owner"


def test_identical_capture_has_no_changed_items():
    snapshot = pair()[0]
    result = compare([snapshot, snapshot])
    assert not result["declaration_changes"]
    assert not result["exposure_changes"]
    assert not result["policy_result_changes"]
    assert not result["configuration_changes"]


@pytest.mark.parametrize(
    "attack", ["foreign_org", "reversed", "same_id", "rehashed_result", "schema"]
)
def test_invalid_comparison_denies(attack):
    snapshots = pair()
    org = None
    if attack == "foreign_org":
        org = uuid4()
    if attack == "reversed":
        snapshots.reverse()
    if attack == "same_id":
        snapshots[1].id = snapshots[0].id
    if attack == "rehashed_result":
        snapshots[1].result_payload["benefit_model"] = {"state": "supplied"}
        snapshots[1].result_sha256 = canonical_sha256(snapshots[1].result_payload)
    if attack == "schema":
        snapshots[1].input_payload["capture_contract"] = "future.capture.v2"
        snapshots[1].input_sha256 = canonical_sha256(snapshots[1].input_payload)
    original = deepcopy(snapshots)
    with pytest.raises(ValueError):
        compare(snapshots, org)
    assert snapshots == original
