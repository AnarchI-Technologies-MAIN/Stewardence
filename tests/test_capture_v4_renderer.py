"""Synthetic v4 semantics and standalone dependency qualification."""

import ast
import builtins
import importlib
from copy import deepcopy
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from apps.reviews.capture_context import digest
from apps.reviews.capture_context_v3 import build_capture_v4_pack_context
from apps.reviews.proposals_v1 import APPLICABILITY_VERSION, build_review_proposals
from renderer.schema import validate_report_render_payload
from renderer.template import render_report_html
from tests.test_capture_review_renderer import capture_projection


def v4_projection(industry="other"):
    metadata, p = capture_projection(industry)
    pin = p["manifest"]["snapshot"]
    envelope = {
        "input_payload": p["snapshot_input"],
        "result_payload": p["snapshot_result"],
        "input_sha256": pin["input_sha256"],
        "result_sha256": pin["result_sha256"],
    }
    proposals = build_review_proposals(
        snapshot_id=UUID(pin["snapshot_id"]), capture_envelope=envelope
    )
    qualification = digest(
        {
            "schema": APPLICABILITY_VERSION,
            "industry_applicability": p["snapshot_input"]["industry_applicability"],
            "ruleset": p["snapshot_input"]["rulesets"]["industry"],
            "engine_versions": p["snapshot_input"]["engine_versions"],
        }
    )
    receipt, revision = str(uuid4()), str(uuid4())
    selected = [
        {
            "proposal_receipt_id": receipt,
            "revision_id": revision,
            "revision_sha256": digest(proposals),
            "card_index": i,
            "card_sha256": digest(proposal),
            "qualification_sha256": qualification,
            "proposal": proposal,
        }
        for i, proposal in enumerate(proposals)
    ]
    p["schema"] = "stewardence.review_worker_projection.v3"
    p["selected_proposals"] = selected
    p["manifest"].update(
        schema="stewardence.review_pack.v4",
        selected_proposals=deepcopy(selected),
        selection_scope="issued_capture_proposals",
        proposal_contract_version="stewardence.core_review_proposal.v1",
    )
    p["manifest_sha256"] = digest(p["manifest"])
    return metadata, p


def add_statements(p):
    entry = p["selected_proposals"][0]
    proposal = entry["proposal"]
    prior = None
    for sequence, (kind, state) in enumerate(
        (("disposition", "act"), ("execution", "completion_recorded")), 1
    ):
        body = {
            "schema": "stewardence.core_decision_event.v2",
            "id": str(uuid4()),
            "organization_id": p["organization_id"],
            "created_by_id": p["snapshot_input"]["created_by_id"],
            "created_at": p["manifest"]["snapshot"]["captured_at"],
            "revision_id": entry["revision_id"],
            "revision_sha256": entry["revision_sha256"],
            "snapshot_id": proposal["snapshot_id"],
            "snapshot_result_sha256": proposal["snapshot_result_sha256"],
            "card_index": 0,
            "card_sha256": entry["card_sha256"],
            "previous_event_id": prior,
            "sequence": sequence,
            "event_kind": kind,
            "state": state,
            "responsible_label": "Named owner",
            "due_date": None,
            "notes": "<script>owner statement</script>",
            "links": ["https://example.invalid/reference"],
            "owner_statement_only": True,
            "resolution_verified": False,
            "proposal_id": proposal["proposal_id"],
            "proposal_sha256": proposal["sha256"],
            "proposal_contract": proposal["schema"],
            "proposal_receipt_id": entry["proposal_receipt_id"],
            "source_class": proposal["source"]["class"],
            "source_identity": proposal["source"]["identity"],
            "source_digest": proposal["source"]["digest"],
            "original_outcome": proposal["original_outcome"],
            "resolution_effect": "none",
            "source_state_immutable": True,
        }
        p["selected_decisions"].append(
            {"event_id": body["id"], "event_sha256": digest(body), "payload": body}
        )
        prior = body["id"]
    p["manifest"]["selected_decisions"] = deepcopy(p["selected_decisions"])
    p["manifest_sha256"] = digest(p["manifest"])


@pytest.mark.parametrize("industry", ["other", "accounting_bookkeeping"])
def test_v4_exact_semantics_disposition_and_execution(industry):
    metadata, p = v4_projection(industry)
    add_statements(p)
    context = build_capture_v4_pack_context(metadata, p)
    assert validate_report_render_payload(context) == context
    html = render_report_html(context)
    assert "disposition: act" in html and "execution: completion_recorded" in html
    assert "Original outcome: UNKNOWN" in html
    assert "&lt;script&gt;owner statement&lt;/script&gt;" in html
    assert "<script>owner statement</script>" not in html
    assert (
        "Risk: not assessed" in html
        and "return on investment have not been modeled" in html
    )


@pytest.mark.parametrize(
    "fault",
    [
        "source",
        "text",
        "digest",
        "index_bool",
        "duplicate",
        "resolution",
        "event_source",
        "event_bool",
        "event_kind",
        "baseline",
        "extra",
        "missing_proposal",
        "proposal_contract",
    ],
)
def test_v4_rehashed_semantic_mutations_rejected(fault):
    metadata, p = v4_projection()
    add_statements(p)
    entry = p["selected_proposals"][0]
    event = p["selected_decisions"][0]
    if fault == "source":
        entry["proposal"]["source"]["identity"] = "permissions"
    if fault == "text":
        entry["proposal"]["proposal_text"] = "Everything is safe"
    if fault == "digest":
        entry["card_sha256"] = entry["proposal"]["sha256"]
    if fault == "index_bool":
        entry["card_index"] = False
    if fault == "duplicate":
        p["selected_decisions"].append(deepcopy(event))
    if fault == "resolution":
        event["payload"]["resolution_verified"] = True
    if fault == "event_source":
        event["payload"]["source_digest"] = "a" * 64
    if fault == "event_bool":
        event["payload"]["sequence"] = True
    if fault == "event_kind":
        event["payload"]["event_kind"] = "provider_write"
    if fault == "baseline":
        p["manifest"]["baseline_pack_id"] = str(uuid4())
    if fault == "extra":
        event["payload"]["extra"] = True
    if fault == "proposal_contract":
        p["manifest"]["proposal_contract_version"] = (
            "stewardence.core_review_proposal.v2"
        )
    if fault == "missing_proposal":
        p["selected_proposals"].pop()
    event["event_sha256"] = digest(event["payload"])
    p["manifest"]["selected_decisions"] = deepcopy(p["selected_decisions"])
    p["manifest"]["selected_proposals"] = deepcopy(p["selected_proposals"])
    p["manifest_sha256"] = digest(p["manifest"])
    with pytest.raises(ValueError):
        build_capture_v4_pack_context(metadata, p)


def test_standalone_cold_import_without_apps(monkeypatch):
    metadata, p = v4_projection()
    context = build_capture_v4_pack_context(metadata, p)
    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "apps" or name.startswith("apps."):
            raise AssertionError("Standalone renderer imported application")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    module = importlib.reload(
        importlib.import_module("renderer.capture_pack_v4_schema")
    )
    for name in (
        "policy_engine",
        "accounting_pack",
        "workflow_profile",
        "capture",
        "exposure",
        "proposals",
    ):
        importlib.reload(importlib.import_module(f"renderer.semantics_v1.{name}"))
    assert module.validate_capture_v4_render_payload(context) == context


@pytest.mark.parametrize(
    "app,standalone",
    [
        ("assessments/policy_engine_v1", "policy_engine"),
        ("assessments/accounting_pack_v1", "accounting_pack"),
        ("assessments/workflow_profile_v1", "workflow_profile"),
        ("assessments/capture_v1", "capture"),
        ("reviews/exposure_v1", "exposure"),
        ("reviews/proposals_v1", "proposals"),
    ],
)
def test_permanent_semantic_bodies_equal(app, standalone):
    root = Path(__file__).resolve().parents[1]

    def bodies(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        tree.body = [
            n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        return ast.dump(tree, include_attributes=False)

    assert bodies(root / "apps" / f"{app}.py") == bodies(
        root / "renderer" / "semantics_v1" / f"{standalone}.py"
    )


def test_v4_oversized_context_denied_without_truncation():
    metadata, p = v4_projection()
    add_statements(p)
    p["selected_decisions"][0]["payload"]["notes"] = "x" * 1_048_576
    event = p["selected_decisions"][0]
    event["event_sha256"] = digest(event["payload"])
    p["manifest"]["selected_decisions"] = deepcopy(p["selected_decisions"])
    p["manifest_sha256"] = digest(p["manifest"])
    with pytest.raises(ValueError, match="too large"):
        build_capture_v4_pack_context(metadata, p)


def test_app_and_standalone_closed_validator_bodies_equal():
    root = Path(__file__).resolve().parents[1]

    def body(relative, name="_validate"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        node = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name
        )
        return ast.dump(node, include_attributes=False)

    assert body("apps/reviews/capture_event_v2.py") == body(
        "renderer/capture_pack_v4_schema.py"
    )
    assert body(
        "apps/reviews/capture_event_v2.py", "_validate_frozen_capture_selection"
    ) == body(
        "renderer/capture_pack_v4_schema.py", "_validate_frozen_capture_selection"
    )


@pytest.mark.parametrize(
    "fault", [None, "unknown_resolved", "proposal_rewrite", "snapshot_pin"]
)
def test_pre_request_selection_validation_without_fabricated_request_metadata(fault):
    from apps.reviews.capture_event_v2 import validate_frozen_capture_selection

    _, p = v4_projection()
    add_statements(p)
    manifest = deepcopy(p["manifest"])
    if fault == "unknown_resolved":
        event = manifest["selected_decisions"][0]
        event["payload"]["resolution_verified"] = True
        event["event_sha256"] = digest(event["payload"])
    if fault == "proposal_rewrite":
        manifest["selected_proposals"][0]["proposal"]["original_outcome"] = "PASS"
    if fault == "snapshot_pin":
        manifest["snapshot"]["workflow_profile_id"] = str(uuid4())
    fields = {
        "manifest": manifest,
        "snapshot_input": p["snapshot_input"],
        "snapshot_result": p["snapshot_result"],
    }
    if fault is None:
        assert validate_frozen_capture_selection(**fields) == manifest
    if fault is not None:
        with pytest.raises(ValueError):
            validate_frozen_capture_selection(**fields)


@pytest.mark.parametrize("tamper", [False, True])
def test_standalone_qualified_accounting_failure_recomputed(monkeypatch, tamper):
    from tests.test_capture_contract import args

    def known_args(industry):
        pins = args(industry)
        row = pins["inventory_records"][0]
        for key, value in {
            "data_categories": ["payroll"],
            "capabilities": ["external_transfer"],
            "human_approval": False,
        }.items():
            row[key] = value
            row["provenance"][key] = "Declared"
        return pins

    monkeypatch.setattr("tests.test_capture_review_renderer.args", known_args)
    metadata, p = v4_projection("accounting_bookkeeping")
    assert any(
        entry["proposal"]["source"]["class"] == "accounting_fail"
        for entry in p["selected_proposals"]
    )
    context = build_capture_v4_pack_context(metadata, p)
    if not tamper:
        assert validate_report_render_payload(context) == context
        return
    # Attacker recomputes every snapshot/manifest hash around a fabricated
    # policy row. Permanent renderer recomputation must still reject it.
    result = context["projection"]["snapshot_result"]
    failed = next(
        row
        for row in result["inventory_results"][0]["policy_results"]
        if row["result"] == "FAIL"
    )
    failed["recommended_remediation"] = "Invented current-policy instruction"
    context["projection"]["manifest"]["snapshot"]["result_sha256"] = digest(result)
    context["metadata"]["result_sha256"] = digest(result)
    context["projection"]["manifest_sha256"] = digest(context["projection"]["manifest"])
    with pytest.raises(ValueError):
        validate_report_render_payload(context)
