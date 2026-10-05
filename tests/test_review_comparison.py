"""Change evidence preserves truth boundaries and does not mutate its sources."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.assessments.snapshots import canonical_sha256
from apps.reviews.comparison import compare_snapshots


def snapshot(org, item):
    inputs = {
        "snapshot_schema_version": 1,
        "organization_id": str(org),
        "inventory": [{"id": str(item), "business_owner": "Alex"}],
        "rulesets": {"industry": "accounting.v1"},
        "risk_configuration": {"version": "risk.v1"},
        "engine_versions": {"policy": "policy.v1"},
        "evidence_references": [],
        "roi": {"hours": "2"},
    }
    results = {
        "snapshot_schema_version": 1,
        "inventory_results": [{"inventory_item_id": str(item), "policy_results": []}],
    }
    return SimpleNamespace(
        id=uuid4(),
        organization_id=org,
        captured_at=datetime(2026, 10, 4, tzinfo=UTC),
        input_payload=inputs,
        result_payload=results,
        input_sha256=canonical_sha256(inputs),
        result_sha256=canonical_sha256(results),
    )


def pin(value):
    value.input_sha256 = canonical_sha256(value.input_payload)
    value.result_sha256 = canonical_sha256(value.result_payload)


@pytest.fixture
def pair():
    org, item = uuid4(), uuid4()
    before = snapshot(org, item)
    after = deepcopy(before)
    after.id = uuid4()
    after.captured_at += timedelta(days=1)
    return org, before, after


def compare(pair):
    org, before, after = pair
    return compare_snapshots(baseline=before, current=after, organization_id=org)


def test_unchanged_inputs_ignore_new_snapshot_identity_and_date(pair):
    result = compare(pair)
    assert result["inventory_changes"] == result["finding_changes"] == []
    assert result["configuration_changes"] == []
    assert result["completion_carry_forward"] is False
    assert result["attribution"] == "not_established"


def test_declarations_and_rule_changes_are_separate_not_causal(pair):
    _, _, after = pair
    after.input_payload["inventory"][0]["business_owner"] = "Other owner"
    after.input_payload["rulesets"]["industry"] = "accounting.v2"
    after.result_payload["inventory_results"][0]["policy_results"] = [
        {"result": "CONCERN"}
    ]
    pin(after)
    original = deepcopy(after.__dict__)
    result = compare(pair)
    assert result["inventory_changes"][0]["fields"] == ["business_owner"]
    assert result["configuration_changes"] == ["rulesets"]
    assert result["finding_changes"][0]["fields"] == ["policy_results"]
    assert result["attribution"] == "not_established"
    assert after.__dict__ == original
    assert compare(pair) == result


def test_missing_field_and_explicit_null_are_distinct_changes(pair):
    _, _, after = pair
    after.input_payload["inventory"][0]["account"] = None
    pin(after)
    assert compare(pair)["inventory_changes"][0]["fields"] == ["account"]


def test_added_and_removed_items_have_explicit_identity_and_digests(pair):
    _, _, after = pair
    after.input_payload["inventory"] = [{"id": str(uuid4())}]
    pin(after)
    changes = compare(pair)["inventory_changes"]
    assert {row["change"] for row in changes} == {"added", "removed"}
    assert all(
        (row["before_sha256"] is None) != (row["after_sha256"] is None)
        for row in changes
    )


@pytest.mark.parametrize(
    "failure", ["tenant", "tamper", "duplicate", "reverse", "bool", "id_type", "tree"]
)
def test_invalid_comparison_denied(pair, failure):
    org, _, after = pair
    if failure == "tenant":
        after.organization_id = uuid4()
    if failure == "tamper":
        after.input_payload["inventory"][0]["business_owner"] = "Forged"
    if failure == "duplicate":
        after.input_payload["inventory"] *= 2
        pin(after)
    if failure == "reverse":
        after.captured_at -= timedelta(days=2)
    if failure == "bool":
        after.input_payload["snapshot_schema_version"] = True
        pin(after)
    if failure == "id_type":
        after.input_payload["inventory"][0]["id"] = 5
        pin(after)
    if failure == "tree":
        after.input_payload = []
        pin(after)
    with pytest.raises(ValueError):
        compare_snapshots(baseline=pair[1], current=after, organization_id=org)
