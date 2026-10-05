"""Pure proposal semantics never qualify database issuance or source truth."""

from copy import deepcopy
from uuid import UUID, uuid4

import pytest

from apps.assessments.capture_v1 import build_capture_payloads
from apps.inventory.provenance import DECLARED
from apps.reviews.proposals_v1 import (
    VERSION,
    build_review_proposals,
    validate_review_proposals,
)
from tests.test_capture_contract import args, record


def capture(industry="other", records=None):
    pins = args(industry, records)
    return pins["assessment_id"], build_capture_payloads(**pins)


def build(identity, envelope):
    return build_review_proposals(snapshot_id=identity, capture_envelope=envelope)


def declare(item, **fields):
    for name, value in fields.items():
        item[name] = value
        item["provenance"][name] = DECLARED
    return item


def test_finite_unknown_allowlist_and_exact_source_pins():
    identity, envelope = capture()
    proposals = build(identity, envelope)
    assert {p["source"]["identity"] for p in proposals} == {
        "business_owner",
        "business_purpose",
        "account_identity",
        "access_removal",
    }
    for proposal in proposals:
        assert proposal["schema"] == VERSION
        assert proposal["original_outcome"] == "UNKNOWN"
        assert proposal["source"]["class"] == "exposure_unknown"
        assert proposal["resolution_effect"] == "none"
        assert proposal["source_state_immutable"] is True
        assert proposal["owner_statement_only"] is True
        assert proposal["resolution_verified"] is False
        assert proposal["snapshot_result_sha256"] == envelope["result_sha256"]
        assert proposal["snapshot_input_sha256"] == envelope["input_sha256"]
        assert proposal["authority"] == "proposal_only"
        assert proposal["verification"] == "not_established"
        assert (
            not {"severity", "risk_score", "due_date", "created_at"} & proposal.keys()
        )
        assert len(proposal["source"]["digest"]) == 64
        assert len(proposal["source"]["definition_sha256"]) == 64
        assert UUID(proposal["proposal_id"]).version == 5


@pytest.mark.parametrize(
    "approval,autonomy,expected",
    [
        (False, 1, "CONCERN"),
        (True, 1, "PASS"),
        (False, 0, "NOT_APPLICABLE"),
    ],
)
def test_only_qualified_concern_maps_approval(approval, autonomy, expected):
    item = declare(
        record(),
        business_owner="Alex",
        business_purpose="Drafts",
        human_approval=approval,
        autonomy_level=autonomy,
        permissions=[],
        capabilities=[],
    )
    identity, envelope = capture(records=[item])
    proposals = build(identity, envelope)
    approval_cards = [p for p in proposals if p["source"]["identity"] == "approval"]
    assert len(approval_cards) == (1 if expected == "CONCERN" else 0)
    if approval_cards:
        assert approval_cards[0]["action_kind"] == "review_declared_boundary"
        assert approval_cards[0]["source"]["class"] == "exposure_concern"
    assert not {"business_owner", "business_purpose"} & {
        p["source"]["identity"] for p in proposals
    }


def test_accounting_fail_requires_exact_frozen_qualification():
    item = declare(
        record(),
        data_categories=["payroll"],
        capabilities=["external_transfer"],
        human_approval=False,
    )
    identity, envelope = capture("accounting_bookkeeping", [item])
    proposals = build(identity, envelope)
    failures = [p for p in proposals if p["source"]["class"] == "accounting_fail"]
    assert {p["source"]["identity"] for p in failures} == {
        "ACC-PAYROLL-EXT",
        "ACC-PAYROLL-EXT-NO-APPROVAL",
    }
    assert {p["severity"] for p in failures} == {"HIGH", "CRITICAL"}
    for proposal in failures:
        assert proposal["action_kind"] == "address_qualified_failure"
        assert proposal["original_outcome"] == "FAIL"
        assert (
            proposal["source"]["definitions_sha256"]
            == envelope["input_payload"]["rulesets"]["industry"]["definitions_sha256"]
        )
        assert len(proposal["source"]["qualification_sha256"]) == 64
    other_id, other = capture("other", [item])
    assert all(
        p["source"]["class"] != "accounting_fail" for p in build(other_id, other)
    )


def test_unknown_premise_does_not_emit_accounting_failure():
    item = declare(record(), data_categories=["payroll"])
    identity, envelope = capture("accounting_bookkeeping", [item])
    assert all(
        p["source"]["class"] != "accounting_fail" for p in build(identity, envelope)
    )


def test_deterministic_order_identity_digest_and_no_aliases():
    identity, envelope = capture(records=[record(UUID(int=2)), record(UUID(int=1))])
    original = deepcopy(envelope)
    first = build(identity, envelope)
    assert first == build(identity, deepcopy(envelope))
    assert [p["inventory_item_id"] for p in first] == sorted(
        p["inventory_item_id"] for p in first
    )
    assert (
        validate_review_proposals(
            snapshot_id=identity, capture_envelope=envelope, proposals=first
        )
        == first
    )
    first[0]["source"]["source_fields"].append("forged")
    assert envelope == original
    assert "forged" not in str(build(identity, envelope))


@pytest.mark.parametrize(
    "change",
    ["question", "digest", "record", "result", "definition", "applicability", "extra"],
)
def test_changed_source_or_semantics_denied(change):
    identity, envelope = capture("accounting_bookkeeping")
    proposals = build(identity, envelope)
    if change == "question":
        proposals[0]["source"]["outcome"] = "PASS"
    elif change == "digest":
        proposals[0]["sha256"] = "a" * 64
    elif change == "extra":
        proposals[0]["verified"] = True
    elif change == "record":
        envelope["input_payload"]["inventory"][0]["display_name"] = "Changed"
    elif change == "result":
        envelope["result_sha256"] = "a" * 64
    elif change == "definition":
        envelope["input_payload"]["rulesets"]["industry"]["definitions_sha256"] = (
            "a" * 64
        )
    elif change == "applicability":
        envelope["input_payload"]["industry_applicability"]["reason"] = "verified"
    with pytest.raises(ValueError):
        validate_review_proposals(
            snapshot_id=identity, capture_envelope=envelope, proposals=proposals
        )


@pytest.mark.parametrize("malformed", [None, True, {}, "2", 2])
def test_strict_snapshot_uuid_type(malformed):
    _, envelope = capture()
    with pytest.raises(ValueError):
        build(malformed, envelope)


def test_changed_snapshot_uuid_and_boolean_admission_shape_denied():
    identity, envelope = capture()
    with pytest.raises(ValueError):
        build(uuid4(), envelope)
    envelope["input_payload"]["assessment"]["version"] = True
    with pytest.raises(ValueError):
        build(identity, envelope)


def test_independent_later_capture_changes_without_rewriting_unknown():
    item = record()
    old_id, old = capture(records=[item])
    before = build(old_id, old)
    declare(item, business_owner="New responsible person")
    new_id, new = capture(records=[item])
    assert not any(
        p["source"]["identity"] == "business_owner" for p in build(new_id, new)
    )
    assert build(old_id, old) == before


def test_fixed_v1_uuid_and_complete_payload_digest_goldens():
    pins = args("other", [record(UUID(int=5))])
    pins.update(
        organization_id=UUID(int=1),
        created_by_id=UUID(int=2),
        assessment_id=UUID(int=3),
        workflow_profile_id=UUID(int=4),
    )
    proposals = build(pins["assessment_id"], build_capture_payloads(**pins))
    # New proposal-v1 semantics lock, not a historical deployment receipt.
    assert [
        (p["source"]["identity"], p["proposal_id"], p["sha256"]) for p in proposals
    ] == [
        (
            "access_removal",
            "e6820559-9b7d-5ea6-9b4e-e9fb9beba217",
            "b4d78f9cf2628fa795a0238ef65dd27ca81d1c76867951146480e4d8b347eccc",
        ),
        (
            "account_identity",
            "57107579-e46d-5740-be02-86550be48442",
            "1caad5b2327b4125e6fde2d8f601b218624e14f8bea4e8ab04a0ad005e65fea6",
        ),
        (
            "business_owner",
            "a2009159-b8d4-5fdf-aacf-fb6e3aeb65a7",
            "9cb7d10df4eabd3b257e19eb0337a2828351947be3d31f436e1d600f3625d80a",
        ),
        (
            "business_purpose",
            "732fccad-5254-5152-869b-eff344f76d0e",
            "94862c45d594d0e5ec284e4234ce1ab089c764a3f9268e267694fd194d6bada7",
        ),
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("contract_version", True),
        ("digest", None),
        ("digest", "A" * 64),
        ("source_fields", None),
        ("source_fields", ["forged"]),
        ("definition_sha256", 0),
        ("class", "accounting_fail"),
    ],
)
def test_source_types_and_forged_identity_deny_even_with_recomputed_self_sha(
    field, value
):
    import hashlib

    import rfc8785

    identity, envelope = capture()
    proposals = build(identity, envelope)
    proposals[0]["source"][field] = value
    payload = {k: v for k, v in proposals[0].items() if k != "sha256"}
    proposals[0]["sha256"] = hashlib.sha256(rfc8785.dumps(payload)).hexdigest()
    with pytest.raises(ValueError):
        validate_review_proposals(
            snapshot_id=identity, capture_envelope=envelope, proposals=proposals
        )


def test_missing_extra_reordered_and_null_proposals_deny():
    identity, envelope = capture()
    proposals = build(identity, envelope)
    for altered in (
        None,
        {},
        proposals[:-1],
        [*proposals, deepcopy(proposals[0])],
        proposals[::-1],
    ):
        with pytest.raises(ValueError):
            validate_review_proposals(
                snapshot_id=identity, capture_envelope=envelope, proposals=altered
            )


def test_bare_default_values_never_become_known_accounting_premises():
    item = record()
    # UNKNOWN provenance with concrete defaults is invalid capture input,
    # rather than permission to evaluate a rule from those defaults.
    item["human_approval"] = False
    item["capabilities"] = ["external_transfer"]
    with pytest.raises(ValueError):
        capture("accounting_bookkeeping", [item])
