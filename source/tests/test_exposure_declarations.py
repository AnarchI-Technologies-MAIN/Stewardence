"""A declaration, a default and a checked control remain different claims."""

from copy import deepcopy
from uuid import uuid4

import pytest

from apps.inventory.provenance import DECLARED, UNKNOWN
from apps.reviews.exposure import Outcome, review_record


@pytest.fixture
def record():
    value = {
        "id": str(uuid4()),
        "business_owner": "Alex",
        "business_purpose": "Draft meeting notes",
        "data_categories": ["client_discussions"],
        "permissions": ["read"],
        "capabilities": ["suggest"],
        "human_approval": True,
        "autonomy_level": 1,
    }
    value["provenance"] = {key: DECLARED for key in value if key != "id"}
    return value


def states(result):
    return {question["question_id"]: question for question in result["questions"]}


def test_recorded_approval_is_not_verification(record):
    result = review_record(record)
    assert states(result)["approval"]["outcome"] == Outcome.PASS
    assert all(q["verification"] == "not_established" for q in result["questions"])
    assert result["authority"] == "proposal_only"
    assert states(result)["account_identity"]["outcome"] == Outcome.UNKNOWN
    assert states(result)["access_removal"]["outcome"] == Outcome.UNKNOWN


def test_collector_defaults_cannot_claim_declared_permissions_or_approval(record):
    record["provenance"] = {key: UNKNOWN for key in record["provenance"]}
    assert all(
        q["outcome"] == Outcome.UNKNOWN for q in review_record(record)["questions"]
    )


def test_missing_provenance_remains_unknown(record):
    record.pop("provenance")
    result = review_record(record)
    assert all(q["outcome"] == Outcome.UNKNOWN for q in result["questions"])
    assert all(q["basis"] == "unknown" for q in result["questions"])


def test_explicit_empty_actions_only_establish_declared_non_applicability(record):
    record.update(capabilities=[], permissions=[], autonomy_level=0)
    assert (
        states(review_record(record))["approval"]["outcome"] == Outcome.NOT_APPLICABLE
    )


def test_unrecognized_action_does_not_mean_no_action(record):
    record.update(capabilities=["future_vendor_operation"], human_approval=False)
    assert states(review_record(record))["approval"]["outcome"] == Outcome.CONCERN


def test_blank_named_owner_needs_a_decision(record):
    record["business_owner"] = " "
    assert states(review_record(record))["business_owner"]["outcome"] == Outcome.CONCERN


@pytest.mark.parametrize(
    "field,value",
    [("permissions", "read"), ("human_approval", 1), ("autonomy_level", True)],
)
def test_wrong_semantic_types_reject(record, field, value):
    record[field] = value
    with pytest.raises(ValueError):
        review_record(record)


def test_review_is_deterministic_and_preserves_input(record):
    before = deepcopy(record)
    first = review_record(record)
    assert review_record(record) == first
    assert record == before
    record["human_approval"] = False
    assert review_record(record)["sha256"] != first["sha256"]
