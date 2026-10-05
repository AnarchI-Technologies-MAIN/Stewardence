"""Historical interpretation compatibility; synthetic projections are not issuance.

These tests exercise a cold context import after mutable aliases change. They
do not promise byte-identical PDFs across Chromium/font/library upgrades.
"""

import builtins
import importlib
from copy import deepcopy
from datetime import datetime
from uuid import UUID

import pytest
import rfc8785

from apps.assessments.capture_v1 import build_capture_payloads
from apps.reviews import capture_context
from renderer import capture_schema
from renderer.schema import validate_report_render_payload
from renderer.template import render_report_html
from tests.test_capture_review_renderer import capture_projection


def known_projection(industry):
    metadata, projection = capture_projection(industry)
    inputs = projection["snapshot_input"]
    row = inputs["inventory"][0]
    for field, value in (
        ("business_owner", "Owner"),
        ("data_categories", ["payroll"]),
        ("capabilities", ["external_transfer"]),
        ("human_approval", False),
    ):
        row[field] = value
        row["provenance"][field] = "Declared"
    profile = inputs["workflow_profile"]
    value = build_capture_payloads(
        organization_id=UUID(inputs["organization_id"]),
        created_by_id=UUID(inputs["created_by_id"]),
        assessment_id=UUID(inputs["assessment"]["id"]),
        assessment_version=1,
        captured_at=datetime.fromisoformat(
            inputs["captured_at"].replace("Z", "+00:00")
        ),
        industry=industry,
        workflow_profile_id=UUID(profile["id"]),
        workflow_profile=profile["profile"],
        workflow_settings=profile["settings"],
        inventory_records=inputs["inventory"],
    )
    projection["snapshot_input"] = value["input_payload"]
    projection["snapshot_result"] = value["result_payload"]
    for field in ("input_sha256", "result_sha256"):
        metadata[field] = value[field]
        projection["manifest"]["snapshot"][field] = value[field]
    projection["manifest_sha256"] = capture_context.digest(projection["manifest"])
    return metadata, projection


def drift_current_aliases(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Historical context touched mutable current semantics")

    monkeypatch.setattr(
        "apps.assessments.capture_contract.CONTRACT", "core.capture.future.v99"
    )
    monkeypatch.setattr(
        "apps.assessments.capture_contract.validate_capture_payloads", forbidden
    )
    monkeypatch.setattr(
        "apps.assessments.capture_contract.build_capture_payloads", forbidden
    )
    monkeypatch.setattr("apps.inventory.provenance.INVENTORY_FACT_FIELDS", ())
    monkeypatch.setattr("apps.inventory.provenance.DECLARED", "Future declaration")
    monkeypatch.setattr("apps.inventory.provenance.UNKNOWN", "Future unknown")
    monkeypatch.setattr("apps.jobs.contracts.validate_branch_settings", forbidden)
    monkeypatch.setattr("apps.policies.engine.evaluate_rule", forbidden)
    monkeypatch.setattr("apps.policies.engine.ENGINE_VERSION", "AL-POLICY-FUTURE")
    monkeypatch.setattr("apps.policies.packs.accounting.ACCOUNTING_RISK_PACK_V1", None)
    monkeypatch.setattr("apps.reviews.exposure.review_record", forbidden)
    monkeypatch.setattr("apps.reviews.exposure.VERSION", "core.exposure.future.v99")


@pytest.mark.parametrize("industry", ["other", "accounting_bookkeeping"])
def test_cold_historical_context_keeps_meaning_after_current_alias_drift(
    industry, monkeypatch
):
    metadata, projection = known_projection(industry)
    expected = capture_context.build_capture_pack_context(metadata, projection)
    expected_bytes = rfc8785.dumps(expected)
    expected_html = render_report_html(expected)
    if industry == "accounting_bookkeeping":
        assert any(
            p["result"] == "FAIL"
            for p in projection["snapshot_result"]["inventory_results"][0][
                "policy_results"
            ]
        )
    with monkeypatch.context() as patch:
        drift_current_aliases(patch)
        try:
            importlib.reload(capture_context)
            replay = capture_context.build_capture_pack_context(metadata, projection)
            assert rfc8785.dumps(replay) == expected_bytes
            assert validate_report_render_payload(replay) == expected
            assert render_report_html(replay) == expected_html
            assert replay["projection"]["manifest"]["selected_decisions"] == []
            assert replay["projection"]["manifest"]["baseline_promotion"] == "blocked"
        finally:
            patch.undo()
            importlib.reload(capture_context)


def test_cold_standalone_renderer_never_imports_application_semantics(monkeypatch):
    payload = capture_context.build_capture_pack_context(*known_projection("other"))
    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "apps" or name.startswith("apps."):
            pytest.fail(f"Standalone renderer imported application semantics: {name}")
        return original_import(name, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "__import__", guarded_import)
        importlib.reload(capture_schema)
        assert capture_schema.validate_capture_render_payload(payload) == payload
        assert "Risk: not assessed" in render_report_html(payload)


def test_alias_drift_does_not_open_v3_decision_selection(monkeypatch):
    metadata, projection = known_projection("other")
    changed = deepcopy(projection)
    changed["manifest"]["selected_decisions"] = [{"proposal_id": str(UUID(int=777))}]
    changed["selected_decisions"] = changed["manifest"]["selected_decisions"]
    changed["manifest_sha256"] = capture_context.digest(changed["manifest"])
    with monkeypatch.context() as patch:
        drift_current_aliases(patch)
        with pytest.raises(ValueError, match="initial selection"):
            capture_context.build_capture_pack_context(metadata, changed)
