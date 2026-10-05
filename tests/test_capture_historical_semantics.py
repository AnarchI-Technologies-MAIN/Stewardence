"""Permanent capture v1 survives changes to current aliases.

Golden hashes were computed from frozen image d3c7519 source, before extraction.
These tests establish interpretation compatibility, not admission or truth.
"""

from uuid import UUID

import pytest

from apps.assessments.capture_v1 import (
    build_capture_payloads,
    validate_capture_payloads,
)
from tests.test_capture_contract import args, record


@pytest.mark.parametrize(
    "industry,input_sha,result_sha",
    [
        (
            "other",
            "dac2763c822baaf708fbb22c46f09ea14917b35991504d89d94a56f6bce54fd8",
            "89370962075734b9dab03348d7aa4d5bf40515f6e58e788b7e33741cbba581c1",
        ),
        (
            "accounting_bookkeeping",
            "fc510a466bb56099dcfa42e86882ef2bb7ffd18b591a439b5a6a3f10e7389eca",
            "77de47e4506d81b034f9faac31d1c446d1acde7902f9dc0b0ded382915281365",
        ),
    ],
)
def test_permanent_capture_ignores_current_semantic_aliases(
    industry, input_sha, result_sha, monkeypatch
):
    item = record(UUID(int=5))
    pins = args(industry, [item])
    pins.update(
        organization_id=UUID(int=1),
        created_by_id=UUID(int=2),
        assessment_id=UUID(int=3),
        workflow_profile_id=UUID(int=4),
    )
    for field, value in (
        ("business_owner", "Owner"),
        ("data_categories", ["payroll"]),
        ("capabilities", ["external_transfer"]),
        ("human_approval", False),
    ):
        item[field] = value
        item["provenance"][field] = "Declared"

    def forbidden(*arguments, **keywords):
        pytest.fail("Historical capture touched current semantic implementation")

    monkeypatch.setattr("apps.inventory.provenance.INVENTORY_FACT_FIELDS", ())
    monkeypatch.setattr("apps.inventory.provenance.DECLARED", "Future declaration")
    monkeypatch.setattr("apps.inventory.provenance.UNKNOWN", "Future unknown")
    monkeypatch.setattr("apps.jobs.contracts.validate_branch_settings", forbidden)
    monkeypatch.setattr("apps.policies.engine.evaluate_rule", forbidden)
    monkeypatch.setattr("apps.policies.engine.ENGINE_VERSION", "AL-POLICY-FUTURE")
    monkeypatch.setattr("apps.policies.packs.accounting.ACCOUNTING_RISK_PACK_V1", None)
    envelope = build_capture_payloads(**pins)
    assert envelope["input_sha256"] == input_sha
    assert envelope["result_sha256"] == result_sha
    assert (
        validate_capture_payloads(
            envelope,
            **{
                key: pins[key]
                for key in ("organization_id", "created_by_id", "workflow_profile_id")
            },
        )
        == envelope
    )
