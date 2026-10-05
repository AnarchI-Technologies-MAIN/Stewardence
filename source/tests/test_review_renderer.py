"""Closed frozen-pack contracts plus genuine offline Chromium PDF rendering.

These fixtures prove render consistency, not admission or provider truth.
"""

import hashlib
import json
from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import pytest
import rfc8785
from playwright.sync_api import sync_playwright
from pypdf import PdfReader
from test_renderer import valid_payload

from apps.reviews.exposure import review_record
from renderer.render import render_pdf
from renderer.schema import InvalidReportRenderPayload, validate_report_render_payload
from renderer.template import render_report_html


def digest(value):
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def review_payload():
    report = valid_payload()
    report.update(
        context_version="AL-REVIEW-PACK-CONTEXT-1",
        title="Frozen AI Evidence Review Pack",
    )
    org, revision, event_id, cycle, pack, actor, item = [str(uuid4()) for _ in range(7)]
    snapshot = report["metadata"]["assessment_snapshot_id"]
    record = {
        "id": item,
        "display_name": "Payroll review assistant",
        "business_owner": "Alex owner",
        "business_purpose": "Draft payroll questions",
        "data_categories": ["payroll"],
        "permissions": ["read"],
        "capabilities": ["draft"],
        "human_approval": False,
        "autonomy_level": 1,
        "provenance": {
            key: "Declared"
            for key in (
                "business_owner",
                "business_purpose",
                "data_categories",
                "permissions",
                "capabilities",
                "human_approval",
                "autonomy_level",
            )
        },
    }
    report["inventory"] = [deepcopy(record)]
    proposal = {
        "inventory_item_id": item,
        "rule_id": "approval-required",
        "rule_version": "1",
        "severity": "high",
        "proposal": "Review the approval boundary",
        "authority": "proposal_only",
    }
    event = {
        "schema": "stewardence.core_decision_event.v1",
        "id": event_id,
        "organization_id": org,
        "created_by_id": actor,
        "created_at": "2026-10-04T12:30:00+00:00",
        "revision_id": revision,
        "revision_sha256": digest([proposal]),
        "snapshot_id": snapshot,
        "snapshot_result_sha256": "a" * 64,
        "card_index": 0,
        "card_sha256": digest(proposal),
        "previous_event_id": None,
        "sequence": 1,
        "event_kind": "execution",
        "state": "completion_recorded",
        "responsible_label": "Alex owner",
        "due_date": "2026-10-12",
        "notes": "Owner statement only: approval review performed.",
        "links": ["https://example.invalid/evidence"],
        "owner_statement_only": True,
        "resolution_verified": False,
    }
    selection = {
        key: event[key]
        for key in (
            "revision_id",
            "revision_sha256",
            "card_index",
            "card_sha256",
            "snapshot_id",
            "snapshot_result_sha256",
            "event_kind",
            "state",
            "owner_statement_only",
            "resolution_verified",
        )
    }
    selection.update(event_id=event_id, event_sha256=digest(event))
    frozen_snapshot = {
        "snapshot_id": snapshot,
        "assessment_id": report["metadata"]["assessment_id"],
        "assessment_version": 1,
        "input_sha256": "a" * 64,
        "result_sha256": "a" * 64,
        "captured_at": report["metadata"]["assessment_date"],
        "snapshot_schema": 1,
        "workflow_profile_id": str(uuid4()),
        "workflow_profile": "business.v1",
        "workflow_settings_sha256": "b" * 64,
        "rules_sha256": "c" * 64,
        "configuration_sha256": "d" * 64,
        "engine_versions": {},
    }
    manifest = {
        "schema": "stewardence.review_pack.v2",
        "cycle_id": cycle,
        "organization_id": org,
        "baseline_pack_id": None,
        "snapshot": frozen_snapshot,
        "selected_decisions": [selection],
        "selection_scope": "owner_statement_events",
        "artifact_state": "not_created",
        "baseline_promotion": "blocked",
    }
    report["review_pack"] = {
        "schema": "stewardence.review_pack_render.v1",
        "pack_id": pack,
        "manifest_sha256": digest(manifest),
        "manifest": manifest,
        "selected_decisions": [
            {
                "selection": deepcopy(selection),
                "payload": event,
                "event_sha256": digest(event),
                "proposal": proposal,
            }
        ],
        "exposure_reviews": [
            {
                "source_record": record,
                "review": json.loads(json.dumps(review_record(record))),
            }
        ],
    }
    return report


def reseal(report):
    pack = report["review_pack"]
    for entry in pack["selected_decisions"]:
        entry["event_sha256"] = digest(entry["payload"])
        entry["selection"]["event_sha256"] = entry["event_sha256"]
    pack["manifest"]["selected_decisions"] = [
        deepcopy(entry["selection"]) for entry in pack["selected_decisions"]
    ]
    pack["manifest_sha256"] = digest(pack["manifest"])


def test_legacy_contract_remains_exact_and_review_contract_is_separate():
    assert (
        validate_report_render_payload(valid_payload())["context_version"]
        == "AL-REPORT-CONTEXT-2"
    )
    assert (
        validate_report_render_payload(review_payload())["context_version"]
        == "AL-REVIEW-PACK-CONTEXT-1"
    )
    old = valid_payload()
    old["review_pack"] = {}
    with pytest.raises(InvalidReportRenderPayload):
        validate_report_render_payload(old)
    new = review_payload()
    new["context_version"] = "AL-REPORT-CONTEXT-2"
    with pytest.raises(InvalidReportRenderPayload):
        validate_report_render_payload(new)


@pytest.mark.parametrize(
    "attack",
    [
        "extra_top",
        "missing_pack",
        "manifest_hash",
        "event_hash",
        "proposal_changed",
        "missing_decision",
        "foreign_snapshot",
        "foreign_org",
        "verified",
        "provider_authority",
        "unknown_state",
        "null_label",
        "eleven_links",
        "http_link",
        "userinfo_link",
        "extra_event",
        "card_bool",
        "duplicate_selection",
        "exposure_record_changed",
        "exposure_review_changed",
        "missing_exposure",
        "verified_exposure",
        "extra_exposure",
        "unknown_question",
        "bad_question_basis",
        "foreign_cycle",
        "snapshot_schema_bool",
        "structured_card_index",
        "structured_state",
        "null_inventory",
        "null_exposure",
        "empty_scope",
        "foreign_proposal_inventory",
        "contradictory_date",
        "contradictory_engines",
    ],
)
def test_review_contract_rejects_tampering_even_self_consistent_unsupported_claims(
    attack,
):
    report = review_payload()
    pack = report["review_pack"]
    entry = pack["selected_decisions"][0]
    event = entry["payload"]
    exposure = pack["exposure_reviews"][0]
    if attack == "extra_top":
        report["other"] = {}
    if attack == "missing_pack":
        del report["review_pack"]
    if attack == "manifest_hash":
        pack["manifest_sha256"] = "0" * 64
    if attack == "event_hash":
        entry["event_sha256"] = "0" * 64
    if attack == "proposal_changed":
        entry["proposal"]["proposal"] = "Different proposal"
    if attack == "missing_decision":
        pack["selected_decisions"] = []
    if attack == "foreign_snapshot":
        event["snapshot_id"] = str(uuid4())
        entry["selection"]["snapshot_id"] = event["snapshot_id"]
        reseal(report)
    if attack == "foreign_org":
        event["organization_id"] = str(uuid4())
        reseal(report)
    if attack == "verified":
        event["resolution_verified"] = True
        entry["selection"]["resolution_verified"] = True
        reseal(report)
    if attack == "provider_authority":
        entry["proposal"]["authority"] = "provider_write"
        event["card_sha256"] = digest(entry["proposal"])
        entry["selection"]["card_sha256"] = event["card_sha256"]
        reseal(report)
    if attack == "unknown_state":
        event["state"] = "remediated"
        entry["selection"]["state"] = "remediated"
        reseal(report)
    if attack == "null_label":
        event["responsible_label"] = None
        reseal(report)
    if attack == "eleven_links":
        event["links"] = ["https://example.invalid"] * 11
        reseal(report)
    if attack == "http_link":
        event["links"] = ["http://example.invalid"]
        reseal(report)
    if attack == "userinfo_link":
        event["links"] = ["https://user:password@example.invalid"]
        reseal(report)
    if attack == "extra_event":
        event["provider_writes_authorized"] = True
        reseal(report)
    if attack == "card_bool":
        event["card_index"] = False
        entry["selection"]["card_index"] = False
        reseal(report)
    if attack == "duplicate_selection":
        pack["selected_decisions"].append(deepcopy(entry))
        reseal(report)
    if attack == "exposure_record_changed":
        exposure["source_record"]["business_purpose"] = "Changed after freeze"
    if attack == "exposure_review_changed":
        exposure["review"]["questions"][0]["explanation"] = "Changed without digest"
    if attack == "missing_exposure":
        pack["exposure_reviews"] = []
    if attack == "verified_exposure":
        exposure["review"]["verification"] = "verified"
        exposure["review"]["sha256"] = digest(
            {k: v for k, v in exposure["review"].items() if k != "sha256"}
        )
    if attack == "extra_exposure":
        exposure["network_scan"] = True
    if attack == "unknown_question":
        exposure["review"]["questions"][0]["question_id"] = "security_guaranteed"
        exposure["review"]["sha256"] = digest(
            {k: v for k, v in exposure["review"].items() if k != "sha256"}
        )
    if attack == "bad_question_basis":
        exposure["review"]["questions"][0]["basis"] = "observed"
        exposure["review"]["sha256"] = digest(
            {k: v for k, v in exposure["review"].items() if k != "sha256"}
        )
    if attack == "foreign_cycle":
        pack["manifest"]["cycle_id"] = "not-a-uuid"
        pack["manifest_sha256"] = digest(pack["manifest"])
    if attack == "snapshot_schema_bool":
        pack["manifest"]["snapshot"]["snapshot_schema"] = True
        pack["manifest_sha256"] = digest(pack["manifest"])
    if attack == "structured_card_index":
        event["card_index"] = []
        entry["selection"]["card_index"] = []
        reseal(report)
    if attack == "structured_state":
        event["state"] = {}
        entry["selection"]["state"] = {}
        reseal(report)
    if attack == "null_inventory":
        report["inventory"] = [None]
    if attack == "null_exposure":
        pack["exposure_reviews"] = [None]
    if attack == "empty_scope":
        pack["manifest"]["selection_scope"] = "empty_initial_kernel"
        pack["manifest_sha256"] = digest(pack["manifest"])
    if attack == "foreign_proposal_inventory":
        entry["proposal"]["inventory_item_id"] = str(uuid4())
        event["card_sha256"] = digest(entry["proposal"])
        entry["selection"]["card_sha256"] = event["card_sha256"]
        reseal(report)
    if attack == "contradictory_date":
        report["assessment_date"] = "2026-10-01T12:00:00Z"
    if attack == "contradictory_engines":
        report["methodology"]["engine_versions"] = {"risk": "different"}
    with pytest.raises(InvalidReportRenderPayload):
        validate_report_render_payload(report)


def test_exact_selection_order_cannot_be_changed_by_renderer_envelope():
    report = review_payload()
    second = deepcopy(report["review_pack"]["selected_decisions"][0])
    second["payload"].update(id=str(uuid4()), card_index=1)
    second["selection"].update(event_id=second["payload"]["id"], card_index=1)
    report["review_pack"]["selected_decisions"].append(second)
    reseal(report)
    validate_report_render_payload(report)
    report["review_pack"]["selected_decisions"].reverse()
    with pytest.raises(InvalidReportRenderPayload):
        validate_report_render_payload(report)


def test_real_chromium_pdf_contains_frozen_identity_exposure_and_owner_statement(
    tmp_path,
):
    report = review_payload()
    pdf = render_pdf(report, output_directory=tmp_path, timeout_seconds=30)
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    for value in (
        "Frozen AI Evidence Review Pack",
        "Exposure review of frozen inputs",
        "Frozen owner decisions",
        "Resolution remains unverified",
        "completion_recorded",
        "approval boundary",
        report["review_pack"]["pack_id"],
        report["review_pack"]["manifest_sha256"],
        report["review_pack"]["selected_decisions"][0]["selection"]["event_id"],
    ):
        assert value in text
    assert pdf.startswith(b"%PDF-")
    assert list(tmp_path.iterdir()) == []


def test_real_chromium_customer_content_and_evidence_links_remain_inert():
    report = review_payload()
    event = report["review_pack"]["selected_decisions"][0]["payload"]
    event["notes"] = (
        '<script>fetch("https://example.invalid/attack")</script><img src="https://example.invalid/leak">'
    )
    reseal(report)
    validate_report_render_payload(report)
    html = render_report_html(report)
    assert "<script>" not in html and '<img src="https:' not in html
    with sync_playwright() as browser_driver:
        browser = browser_driver.chromium.launch(headless=True, chromium_sandbox=False)
        context = browser.new_context(
            java_script_enabled=False, service_workers="block"
        )
        requests = []
        context.on("request", lambda request: requests.append(request.url))
        context.route("**/*", lambda route: route.abort())
        page = context.new_page()
        page.set_content(html, wait_until="load")
        assert page.locator("a[href],script").count() == 0
        assert page.locator("body").inner_text().find(event["notes"]) != -1
        assert requests == []
        context.close()
        browser.close()
