"""Pure synthetic capture projection tests; SQL issuance qualified separately."""

from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import pytest
from pypdf import PdfReader
from test_capture_contract import args

from apps.assessments.capture_contract import build_capture_payloads
from apps.reviews.capture_context import build_capture_pack_context, digest
from renderer.render import render_pdf
from renderer.schema import InvalidReportRenderPayload, validate_report_render_payload
from renderer.template import render_report_html


def capture_projection(industry="other"):
    pins = args(industry)
    envelope = build_capture_payloads(**pins)
    inputs, results = envelope["input_payload"], envelope["result_payload"]
    snapshot = {
        "snapshot_id": inputs["assessment"]["id"],
        "assessment_id": inputs["assessment"]["id"],
        "assessment_version": 1,
        "input_sha256": envelope["input_sha256"],
        "result_sha256": envelope["result_sha256"],
        "captured_at": inputs["captured_at"],
        "snapshot_schema": 2,
        "workflow_profile_id": str(pins["workflow_profile_id"]),
        "workflow_profile": pins["workflow_profile"],
        "workflow_settings_sha256": inputs["workflow_profile"]["settings_sha256"],
        "rules_sha256": digest(inputs["rulesets"]),
        "configuration_sha256": digest(inputs["risk_configuration"]),
        "engine_versions": inputs["engine_versions"],
        "capture_contract": inputs["capture_contract"],
    }
    manifest = {
        "schema": "stewardence.review_pack.v3",
        "cycle_id": str(uuid4()),
        "organization_id": str(pins["organization_id"]),
        "baseline_pack_id": None,
        "snapshot": snapshot,
        "selected_decisions": [],
        "selection_scope": "empty_capture_kernel",
        "artifact_state": "not_created",
        "baseline_promotion": "blocked",
        "capture": {
            "receipt_id": snapshot["snapshot_id"],
            "request_sha256": "b" * 64,
            "contract": "core.capture.declarations.v1",
            "exposure_contract": "core.exposure.declarations.v1",
        },
    }
    projection = {
        "schema": "stewardence.review_worker_projection.v2",
        **{
            key: str(uuid4())
            for key in ("request_id", "job_id", "report_id", "pack_id")
        },
        "organization_id": str(pins["organization_id"]),
        "manifest": manifest,
        "manifest_sha256": digest(manifest),
        "snapshot_input": inputs,
        "snapshot_result": results,
        "selected_decisions": [],
    }
    metadata = {
        "report_identifier": "AL-2026-000001",
        "organization_display_name": "Synthetic owner firm",
        "assessment_date": snapshot["captured_at"],
        "assessment_id": snapshot["assessment_id"],
        "assessment_version": 1,
        "assessment_snapshot_id": snapshot["snapshot_id"],
        "input_sha256": snapshot["input_sha256"],
        "result_sha256": snapshot["result_sha256"],
    }
    return metadata, projection


@pytest.mark.parametrize(
    "industry",
    [
        "other",
        "legal",
        "healthcare",
        "construction",
        "agency",
        "accounting_bookkeeping",
    ],
)
def test_capture_context_exact_unknowns_and_no_legacy_roi(industry):
    metadata, projection = capture_projection(industry)
    context = build_capture_pack_context(metadata, projection)
    assert validate_report_render_payload(context) == context
    assert "roi" not in context and "risk_overview" not in context
    html = render_report_html(context)
    assert "Risk: not assessed" in html and "Benefit model: not supplied" in html
    assert "Generic exposure review" in html and "Unknown / not supplied" in html
    assert "Low" not in html
    original = deepcopy(projection)
    context["projection"]["snapshot_input"]["inventory"][0]["display_name"] = "mutated"
    assert projection == original


@pytest.mark.parametrize(
    "fault",
    [
        "mixed_schema",
        "legacy_manifest",
        "nonempty_decisions",
        "rule_pin",
        "owner",
        "fabricated_risk",
        "fabricated_benefit",
    ],
)
def test_capture_mutations_rejected_before_render(fault):
    metadata, p = capture_projection()
    if fault == "mixed_schema":
        p["snapshot_result"]["snapshot_schema_version"] = 1
    elif fault == "legacy_manifest":
        p["manifest"]["schema"] = "stewardence.review_pack.v2"
    elif fault == "nonempty_decisions":
        p["selected_decisions"] = [{}]
    elif fault == "rule_pin":
        p["manifest"]["snapshot"]["rules_sha256"] = "a" * 64
    elif fault == "owner":
        p["snapshot_input"]["organization_id"] = str(uuid4())
    elif fault == "fabricated_risk":
        p["snapshot_result"]["inventory_results"][0]["risk"] = {
            "state": "assessed",
            "score": 0,
            "band": "Low",
        }
    elif fault == "fabricated_benefit":
        p["snapshot_result"]["benefit_model"] = {"state": "modeled", "roi": 0}
    p["manifest_sha256"] = digest(p["manifest"])
    with pytest.raises(ValueError):
        build_capture_pack_context(metadata, p)


def test_renderer_rejects_extra_roi_and_hash_consistent_fake_risk():
    context = build_capture_pack_context(*capture_projection())
    context["roi"] = {"roi_percent": "0"}
    with pytest.raises(InvalidReportRenderPayload):
        validate_report_render_payload(context)
    context.pop("roi")
    p = context["projection"]
    p["snapshot_result"]["inventory_results"][0]["risk"]["score"] = 0
    pin = p["manifest"]["snapshot"]
    pin["result_sha256"] = digest(p["snapshot_result"])
    context["metadata"]["result_sha256"] = pin["result_sha256"]
    p["manifest_sha256"] = digest(p["manifest"])
    with pytest.raises(InvalidReportRenderPayload, match="risk/policy"):
        validate_report_render_payload(context)


def test_actual_chromium_capture_pack_is_roi_free(tmp_path):
    context = build_capture_pack_context(*capture_projection())
    data = render_pdf(context, output_directory=tmp_path)
    text = " ".join(
        " ".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(data)).pages
        ).split()
    )
    assert data.startswith(b"%PDF-")
    for phrase in (
        "Generic exposure review",
        "Risk: not assessed",
        "Benefit model: not supplied",
        "No qualified industry policy pack",
        "Unknown / not supplied",
        "Frozen pack receipts",
    ):
        assert phrase in text
    assert "Low" not in text and "ROI %" not in text


def test_rehashed_divergent_receipt_identity_cannot_render():
    metadata, p = capture_projection()
    context = build_capture_pack_context(metadata, p)
    p["manifest"]["capture"]["receipt_id"] = str(uuid4())
    p["manifest_sha256"] = digest(p["manifest"])
    with pytest.raises(ValueError, match="receipt snapshot"):
        build_capture_pack_context(metadata, p)
    context["projection"] = p
    with pytest.raises(InvalidReportRenderPayload, match="receipt snapshot"):
        validate_report_render_payload(context)


def test_rehashed_unknown_to_pass_exposure_cannot_render():
    context = build_capture_pack_context(*capture_projection())
    exposure = context["exposure_reviews"][0]
    exposure["questions"][0].update(outcome="PASS", basis="customer_declaration")
    exposure["sha256"] = digest({k: v for k, v in exposure.items() if k != "sha256"})
    with pytest.raises(InvalidReportRenderPayload, match="declaration semantics"):
        validate_report_render_payload(context)


@pytest.mark.parametrize("version", [True, 1.0, "1", None, 2])
def test_metadata_assessment_version_is_exact_integer_one(version):
    metadata, projection = capture_projection()
    context = build_capture_pack_context(metadata, projection)
    metadata["assessment_version"] = version
    with pytest.raises(ValueError, match="integer one"):
        build_capture_pack_context(metadata, projection)
    context["metadata"] = metadata
    rejection = (
        "^Payload contains an unsupported value type$"
        if type(version) is float
        else "integer one"
    )
    with pytest.raises(InvalidReportRenderPayload, match=rejection):
        validate_report_render_payload(context)


def test_initial_capture_pack_rejects_rehashed_unadmitted_baseline():
    metadata, projection = capture_projection()
    context = build_capture_pack_context(metadata, projection)
    projection["manifest"]["baseline_pack_id"] = str(uuid4())
    projection["manifest_sha256"] = digest(projection["manifest"])
    with pytest.raises(ValueError, match="no admitted baseline"):
        build_capture_pack_context(metadata, projection)
    context["projection"] = projection
    with pytest.raises(InvalidReportRenderPayload, match="no admitted baseline"):
        validate_report_render_payload(context)
