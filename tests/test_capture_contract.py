"""Pure capture tests do not establish database issuance or input truth."""

from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from apps.assessments.capture_contract import (
    build_capture_payloads,
    validate_capture_payloads,
)
from apps.inventory.provenance import DECLARED, INVENTORY_FACT_FIELDS, UNKNOWN


def record(identity=None):
    return {
        "id": str(identity or uuid4()),
        "product_id": None,
        **dict.fromkeys(INVENTORY_FACT_FIELDS),
        "display_name": "Tool",
        "source_type": "manual",
        "declaration_contract": "core.inventory.declarations.v1",
        "declaration_as_of": "2026-10-04",
        "archived_at": None,
        "provenance": {
            **{
                field: DECLARED if field == "display_name" else UNKNOWN
                for field in INVENTORY_FACT_FIELDS
            },
            "product_id": UNKNOWN,
            "source_type": DECLARED,
        },
    }


def args(industry="accounting_bookkeeping", records=None):
    return dict(
        organization_id=uuid4(),
        created_by_id=uuid4(),
        assessment_id=uuid4(),
        assessment_version=1,
        captured_at=datetime(2026, 10, 4, 12, tzinfo=UTC),
        industry=industry,
        workflow_profile_id=uuid4(),
        workflow_profile="business.v1",
        workflow_settings={"name": "Company"},
        inventory_records=[record()] if records is None else records,
    )


def verify(envelope, pins):
    return validate_capture_payloads(
        envelope,
        **{
            key: pins[key]
            for key in ("organization_id", "created_by_id", "workflow_profile_id")
        },
    )


@pytest.mark.parametrize(
    "industry",
    [
        "accounting_bookkeeping",
        "legal",
        "healthcare",
        "construction",
        "agency",
        "other",
    ],
)
def test_all_audiences_unknown_benefit_risk_and_applicability(industry):
    pins = args(industry)
    value = build_capture_payloads(**pins)
    assert verify(value, pins) == value
    inputs, results = value["input_payload"], value["result_payload"]
    assert "roi" not in inputs and "roi" not in results
    assert (
        inputs["benefit_model"] == results["benefit_model"] == {"state": "not_supplied"}
    )
    assert not {"risk", "roi"} & inputs["engine_versions"].keys()
    assert inputs["evidence_references"] == []
    row = results["inventory_results"][0]
    assert row["risk"] == {"state": "not_assessed", "score": None, "band": None}
    if industry == "accounting_bookkeeping":
        assert all(
            p["result"] == "UNKNOWN"
            and not p["effects"]
            and p["recommended_remediation"] is None
            for p in row["policy_results"]
        )
        assert inputs["rulesets"]["industry"]["definitions"]
    else:
        assert row["policy_results"] == [] and inputs["rulesets"]["industry"] is None
        assert "policy" not in inputs["engine_versions"]


def test_order_duplicates_count_and_no_alias():
    records = [record(UUID(int=2)), record(UUID(int=1))]
    pins = args(records=records)
    first = build_capture_payloads(**pins)
    pins["inventory_records"] = records[::-1]
    assert first == build_capture_payloads(**pins)
    assert first["input_payload"]["inventory"][0]["id"] == str(UUID(int=1))
    records[0]["display_name"] = "Changed"
    assert "Changed" not in str(first)
    first["input_payload"]["benefit_model"]["state"] = "changed"
    assert first["result_payload"]["benefit_model"] == {"state": "not_supplied"}
    item = record()
    with pytest.raises(ValueError, match="Duplicate"):
        build_capture_payloads(**args(records=[item, deepcopy(item)]))
    assert (
        len(
            build_capture_payloads(**args("other", [record() for _ in range(100)]))[
                "input_payload"
            ]["inventory"]
        )
        == 100
    )


@pytest.mark.parametrize("count", [0, 101])
def test_bounds(count):
    with pytest.raises(ValueError):
        build_capture_payloads(**args(records=[record() for _ in range(count)]))


def test_known_premises_and_auxiliary_unknowns():
    item = record()
    for field, value in {
        "data_categories": ["payroll"],
        "capabilities": ["external_transfer"],
        "human_approval": False,
    }.items():
        item[field] = value
        item["provenance"][field] = DECLARED
    policies = {
        p["rule_id"]: p
        for p in build_capture_payloads(**args(records=[item]))["result_payload"][
            "inventory_results"
        ][0]["policy_results"]
    }
    assert policies["ACC-PAYROLL-EXT"]["result"] == "FAIL"
    assert policies["ACC-PAYROLL-EXT-NO-APPROVAL"]["result"] == "FAIL"
    assert any(
        p["missing_fields"] == ["vendor_review_status"] and p["result"] == "UNKNOWN"
        for p in policies.values()
    )


def test_false_known_premise_does_not_mask_unknown():
    item = record()
    item["data_categories"] = []
    item["provenance"]["data_categories"] = DECLARED

    def outcome():
        return next(
            p["result"]
            for p in build_capture_payloads(**args(records=[item]))["result_payload"][
                "inventory_results"
            ][0]["policy_results"]
            if p["rule_id"] == "ACC-PAYROLL-EXT"
        )

    assert outcome() == "UNKNOWN"
    item["capabilities"] = []
    item["provenance"]["capabilities"] = DECLARED
    assert outcome() == "NOT_APPLICABLE"


@pytest.mark.parametrize(
    "field,value,basis",
    [
        ("permissions", [], UNKNOWN),
        ("human_approval", False, UNKNOWN),
        ("monthly_cost_cents", 0, UNKNOWN),
        ("seat_count", True, DECLARED),
        ("autonomy_level", 5, DECLARED),
        ("human_approval", 0, DECLARED),
        ("permissions", "write", DECLARED),
        ("permissions", ["write", "write"], DECLARED),
        ("vendor_name", None, DECLARED),
    ],
)
def test_invalid_knowledge_types(field, value, basis):
    item = record()
    item[field] = value
    item["provenance"][field] = basis
    with pytest.raises(ValueError):
        build_capture_payloads(**args(records=[item]))


@pytest.mark.parametrize(
    "key,value",
    [
        ("assessment_version", True),
        ("assessment_version", 2),
        ("industry", "unknown"),
        ("workflow_profile", "custom.v1"),
        ("organization_id", "uuid"),
        ("captured_at", datetime(2026, 10, 4)),
    ],
)
def test_bad_pins(key, value):
    pins = args()
    pins[key] = value
    with pytest.raises(ValueError):
        build_capture_payloads(**pins)


@pytest.mark.parametrize(
    "change",
    [
        "schema",
        "digest",
        "result",
        "roi",
        "created_by_id",
        "workflow_profile_id",
        "organization_id",
    ],
)
def test_exact_recompute_rejects_tamper_and_foreign_pins(change):
    pins = args()
    value = build_capture_payloads(**pins)
    if change == "schema":
        value["input_payload"]["snapshot_schema_version"] = True
    elif change == "digest":
        value["input_sha256"] = "0" * 64
    elif change == "result":
        value["result_payload"]["inventory_results"][0]["risk"]["score"] = 0
    elif change == "roi":
        value["input_payload"]["roi"] = {"hours_saved": 0}
    else:
        pins[change] = uuid4()
    with pytest.raises(ValueError):
        verify(value, pins)


@pytest.mark.parametrize(
    "change", ["extra", "future", "catalog", "archived", "missing"]
)
def test_closed_record(change):
    item = record()
    if change == "extra":
        item["organization_id"] = str(uuid4())
    elif change == "future":
        item["declaration_as_of"] = "2026-10-05"
    elif change == "catalog":
        item["product_id"] = str(uuid4())
    elif change == "archived":
        item["archived_at"] = "2026-10-04"
    else:
        item.pop("permissions")
    with pytest.raises(ValueError):
        build_capture_payloads(**args(records=[item]))


def test_actual_inventory_helper_normalizes_unknowns_without_database():
    from datetime import date
    from types import SimpleNamespace

    from apps.inventory.explicit_declarations import (
        normalized_explicit_inventory_record,
    )

    item = SimpleNamespace(
        id=uuid4(),
        product_id=None,
        source_type="manual",
        archived_at=None,
        declaration_contract="core.inventory.declarations.v1",
        declaration_as_of=date(2026, 10, 4),
        declared_fields=["display_name"],
        **{
            field: "Tool" if field == "display_name" else []
            for field in INVENTORY_FACT_FIELDS
        },
    )
    normalized = normalized_explicit_inventory_record(item)
    assert normalized["permissions"] is None
    assert build_capture_payloads(**args("other", [normalized]))["input_payload"][
        "inventory"
    ] == [normalized]


@pytest.mark.parametrize(
    "field,value",
    [("permissions", []), ("human_approval", False), ("monthly_cost_cents", 0)],
)
def test_explicit_none_false_zero_are_preserved_without_benefit(field, value):
    item = record()
    item[field] = value
    item["provenance"][field] = DECLARED
    envelope = build_capture_payloads(**args("other", [item]))
    assert envelope["input_payload"]["inventory"][0][field] == value
    assert envelope["result_payload"]["benefit_model"] == {"state": "not_supplied"}


@pytest.mark.parametrize(
    "value", [None, True, "2026-10-04T00:00:00Z", "20261004", "not-a-date"]
)
def test_declaration_as_of_is_an_exact_owner_date(value):
    item = record()
    item["declaration_as_of"] = value
    with pytest.raises(ValueError):
        build_capture_payloads(**args(records=[item]))


def test_development_profile_and_timezone_normalization_are_pinned():
    from datetime import timedelta, timezone

    pins = args("other")
    pins["workflow_profile"] = "development.v1"
    pins["workflow_settings"] = {
        "name": "Code",
        "repository_ref": "org/repository",
        "environment": "preview",
    }
    first = build_capture_payloads(**pins)
    pins["captured_at"] = pins["captured_at"].astimezone(timezone(timedelta(hours=5)))
    assert first == build_capture_payloads(**pins)
    assert first["input_payload"]["workflow_profile"]["profile"] == "development.v1"


@pytest.mark.parametrize("length,allowed", [(4096, True), (4097, False)])
def test_business_purpose_bound_matches_explicit_issuer(length, allowed):
    item = record()
    item["business_purpose"] = "x" * length
    item["provenance"]["business_purpose"] = DECLARED
    if allowed:
        assert (
            build_capture_payloads(**args("other", [item]))["input_payload"][
                "inventory"
            ][0]["business_purpose"]
            == item["business_purpose"]
        )
    else:
        with pytest.raises(ValueError):
            build_capture_payloads(**args("other", [item]))
