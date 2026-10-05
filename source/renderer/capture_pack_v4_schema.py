"""Closed standalone successor; deterministic consistency is not issuance."""

import json
import re
from copy import deepcopy
from datetime import date, datetime
from uuid import UUID

from .capture_schema import validate_capture_render_payload
from .schema import (
    MAX_PAYLOAD_BYTES,
    InvalidReportRenderPayload,
    _closed,
    _digest,
    _sha,
    _timestamp,
    _uuid,
    _validate_tree,
)
from .semantics_v1.capture import validate_capture_payloads
from .semantics_v1.exposure import review_record
from .semantics_v1.proposals import APPLICABILITY_VERSION, build_review_proposals

VERSION = "AL-REVIEW-PACK-CONTEXT-3"
PROPOSAL_KEYS = {
    "proposal_receipt_id",
    "revision_id",
    "revision_sha256",
    "card_index",
    "card_sha256",
    "qualification_sha256",
    "proposal",
}
EVENT_KEYS = {
    "schema",
    "id",
    "organization_id",
    "created_by_id",
    "created_at",
    "revision_id",
    "revision_sha256",
    "snapshot_id",
    "snapshot_result_sha256",
    "card_index",
    "card_sha256",
    "previous_event_id",
    "sequence",
    "event_kind",
    "state",
    "responsible_label",
    "due_date",
    "notes",
    "links",
    "owner_statement_only",
    "resolution_verified",
    "proposal_id",
    "proposal_sha256",
    "proposal_contract",
    "proposal_receipt_id",
    "source_class",
    "source_identity",
    "source_digest",
    "original_outcome",
    "resolution_effect",
    "source_state_immutable",
}


def legacy_capture(report):
    """Private validation view; never emitted or used as an admitted manifest."""
    value = deepcopy(report)
    value["context_version"] = "AL-REVIEW-PACK-CONTEXT-2"
    p = value["projection"]
    p["schema"] = "stewardence.review_worker_projection.v2"
    p.pop("selected_proposals")
    p["selected_decisions"] = []
    m = p["manifest"]
    m["schema"] = "stewardence.review_pack.v3"
    m.pop("selected_proposals")
    m.pop("proposal_contract_version")
    m["selected_decisions"] = []
    m["selection_scope"] = "empty_capture_kernel"
    p["manifest_sha256"] = _digest(m)
    return value


def validate_capture_v4_render_payload(report):
    try:
        return _validate(report)
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        if isinstance(error, InvalidReportRenderPayload):
            raise
        raise InvalidReportRenderPayload("Malformed capture v4 contract") from error


def _validate(report):
    _closed(
        report,
        {"context_version", "title", "metadata", "projection", "exposure_reviews"},
    )
    if (
        report["context_version"] != VERSION
        or report["title"] != "Frozen Tool Exposure Evidence Pack"
    ):
        raise InvalidReportRenderPayload("Unsupported capture v4 context")
    if (
        len(
            json.dumps(
                report, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode()
        )
        > MAX_PAYLOAD_BYTES
    ):
        raise InvalidReportRenderPayload("Payload is too large")
    _validate_tree(report)
    p = report["projection"]
    _closed(
        p,
        {
            "schema",
            "request_id",
            "job_id",
            "report_id",
            "organization_id",
            "pack_id",
            "manifest",
            "manifest_sha256",
            "snapshot_input",
            "snapshot_result",
            "selected_proposals",
            "selected_decisions",
        },
    )
    m = p["manifest"]
    _closed(
        m,
        {
            "schema",
            "cycle_id",
            "organization_id",
            "baseline_pack_id",
            "snapshot",
            "capture",
            "proposal_contract_version",
            "selected_proposals",
            "selected_decisions",
            "selection_scope",
            "artifact_state",
            "baseline_promotion",
        },
    )
    if (
        p["schema"] != "stewardence.review_worker_projection.v3"
        or m["schema"] != "stewardence.review_pack.v4"
        or m["selection_scope"] != "issued_capture_proposals"
        or m["proposal_contract_version"] != "stewardence.core_review_proposal.v1"
        or _digest(m) != p["manifest_sha256"]
    ):
        raise InvalidReportRenderPayload("Capture v4 manifest mismatch")
    for name in ("selected_proposals", "selected_decisions"):
        if type(p[name]) is not list or p[name] != m[name]:
            raise InvalidReportRenderPayload("Capture v4 frozen selection mismatch")
    validate_capture_render_payload(legacy_capture(report))
    validate_frozen_capture_selection(
        manifest=m,
        snapshot_input=p["snapshot_input"],
        snapshot_result=p["snapshot_result"],
    )
    exposures = json.loads(
        json.dumps([review_record(row) for row in p["snapshot_input"]["inventory"]])
    )
    if report["exposure_reviews"] != exposures:
        raise InvalidReportRenderPayload("Permanent exposure meaning mismatch")
    return report


def validate_frozen_capture_selection(*, manifest, snapshot_input, snapshot_result):
    try:
        return _validate_frozen_capture_selection(
            manifest=manifest,
            snapshot_input=snapshot_input,
            snapshot_result=snapshot_result,
        )
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        if isinstance(error, InvalidReportRenderPayload):
            raise
        raise InvalidReportRenderPayload(
            "Malformed frozen capture selection"
        ) from error


def _validate_frozen_capture_selection(*, manifest, snapshot_input, snapshot_result):
    """Pure pre-request validation. Does not prove admitted database issuance."""
    m = manifest
    _closed(
        m,
        {
            "schema",
            "cycle_id",
            "organization_id",
            "baseline_pack_id",
            "snapshot",
            "capture",
            "selected_proposals",
            "selected_decisions",
            "selection_scope",
            "artifact_state",
            "baseline_promotion",
            "proposal_contract_version",
        },
    )
    if (
        m["schema"] != "stewardence.review_pack.v4"
        or m["proposal_contract_version"] != "stewardence.core_review_proposal.v1"
        or m["selection_scope"] != "issued_capture_proposals"
        or m["artifact_state"] != "not_created"
        or m["baseline_promotion"] != "blocked"
        or m["baseline_pack_id"] is not None
    ):
        raise InvalidReportRenderPayload("Frozen capture v4 meaning invalid")
    _uuid(m["cycle_id"])
    _uuid(m["organization_id"])
    capture, pin = m["capture"], m["snapshot"]
    _closed(capture, {"receipt_id", "request_sha256", "contract", "exposure_contract"})
    _uuid(capture["receipt_id"])
    _sha(capture["request_sha256"])
    if (
        capture["contract"] != "core.capture.declarations.v1"
        or capture["exposure_contract"] != "core.exposure.declarations.v1"
    ):
        raise InvalidReportRenderPayload("Frozen capture contract invalid")
    _closed(
        pin,
        {
            "snapshot_id",
            "assessment_id",
            "assessment_version",
            "input_sha256",
            "result_sha256",
            "captured_at",
            "snapshot_schema",
            "workflow_profile_id",
            "workflow_profile",
            "workflow_settings_sha256",
            "rules_sha256",
            "configuration_sha256",
            "engine_versions",
            "capture_contract",
        },
    )
    for field in ("snapshot_id", "assessment_id", "workflow_profile_id"):
        _uuid(pin[field])
    for field in (
        "input_sha256",
        "result_sha256",
        "workflow_settings_sha256",
        "rules_sha256",
        "configuration_sha256",
    ):
        _sha(pin[field])
    _timestamp(pin["captured_at"])
    if (
        type(pin["assessment_version"]) is not int
        or pin["assessment_version"] != 1
        or type(pin["snapshot_schema"]) is not int
        or pin["snapshot_schema"] != 2
        or pin["capture_contract"] != "core.capture.declarations.v1"
        or capture["receipt_id"] != pin["snapshot_id"]
        or pin["snapshot_id"] != pin["assessment_id"]
    ):
        raise InvalidReportRenderPayload("Frozen capture snapshot identity invalid")
    inputs = snapshot_input
    validate_capture_payloads(
        {
            "input_payload": inputs,
            "result_payload": snapshot_result,
            "input_sha256": pin["input_sha256"],
            "result_sha256": pin["result_sha256"],
        },
        organization_id=UUID(m["organization_id"]),
        created_by_id=UUID(inputs["created_by_id"]),
        workflow_profile_id=UUID(pin["workflow_profile_id"]),
    )
    if (
        inputs["assessment"]
        != {"id": pin["assessment_id"], "version": pin["assessment_version"]}
        or inputs["captured_at"] != pin["captured_at"]
        or inputs["workflow_profile"]["id"] != pin["workflow_profile_id"]
        or inputs["workflow_profile"]["profile"] != pin["workflow_profile"]
        or inputs["workflow_profile"]["settings_sha256"]
        != pin["workflow_settings_sha256"]
        or _digest(inputs["rulesets"]) != pin["rules_sha256"]
        or _digest(inputs["risk_configuration"]) != pin["configuration_sha256"]
        or inputs["engine_versions"] != pin["engine_versions"]
    ):
        raise InvalidReportRenderPayload("Frozen capture snapshot semantics mismatch")
    if (
        type(m["selected_proposals"]) is not list
        or type(m["selected_decisions"]) is not list
    ):
        raise InvalidReportRenderPayload("Frozen capture selection must be arrays")
    p = {
        "manifest": m,
        "snapshot_input": inputs,
        "snapshot_result": snapshot_result,
        "organization_id": m["organization_id"],
        "selected_proposals": m["selected_proposals"],
        "selected_decisions": m["selected_decisions"],
    }
    pin = m["snapshot"]
    envelope = {
        "input_payload": p["snapshot_input"],
        "result_payload": p["snapshot_result"],
        "input_sha256": pin["input_sha256"],
        "result_sha256": pin["result_sha256"],
    }
    expected = build_review_proposals(
        snapshot_id=UUID(pin["snapshot_id"]), capture_envelope=envelope
    )
    selected = p["selected_proposals"]
    if len(selected) != len(expected):
        raise InvalidReportRenderPayload("Complete issued proposal scope required")
    qualification = _digest(
        {
            "schema": APPLICABILITY_VERSION,
            "industry_applicability": p["snapshot_input"]["industry_applicability"],
            "ruleset": p["snapshot_input"]["rulesets"]["industry"],
            "engine_versions": p["snapshot_input"]["engine_versions"],
        }
    )
    revision = _digest(expected)
    common = None
    for index, (entry, proposal) in enumerate(zip(selected, expected, strict=True)):
        _closed(entry, PROPOSAL_KEYS)
        _uuid(entry["proposal_receipt_id"])
        _uuid(entry["revision_id"])
        for key in ("revision_sha256", "card_sha256", "qualification_sha256"):
            _sha(entry[key])
        if (
            type(entry["card_index"]) is not int
            or entry["card_index"] != index
            or entry["proposal"] != proposal
            or entry["card_sha256"] != _digest(proposal)
            or entry["revision_sha256"] != revision
            or entry["qualification_sha256"] != qualification
        ):
            raise InvalidReportRenderPayload(
                "Permanent proposal semantics or pins mismatch"
            )
        identity = (entry["proposal_receipt_id"], entry["revision_id"])
        if common is not None and identity != common:
            raise InvalidReportRenderPayload("Mixed proposal issuance identities")
        common = identity
    seen = set()
    ordering = []
    for item in p["selected_decisions"]:
        _closed(item, {"event_id", "event_sha256", "payload"})
        event = item["payload"]
        _closed(event, EVENT_KEYS)
        _uuid(item["event_id"])
        _sha(item["event_sha256"])
        if type(event["card_index"]) is not int or not 0 <= event["card_index"] < len(
            selected
        ):
            raise InvalidReportRenderPayload("Decision proposal index invalid")
        entry = selected[event["card_index"]]
        proposal = entry["proposal"]
        key = (event["card_index"], event["event_kind"])
        if (
            key in seen
            or event["schema"] != "stewardence.core_decision_event.v2"
            or item["event_id"] != event["id"]
            or item["event_sha256"] != _digest(event)
        ):
            raise InvalidReportRenderPayload("Decision identity or digest mismatch")
        seen.add(key)
        if type(event["sequence"]) is not int or event["sequence"] < 1:
            raise InvalidReportRenderPayload("Decision sequence invalid")
        ordering.append((*key, event["sequence"]))
        for field, expected_value in {
            "organization_id": p["organization_id"],
            "created_by_id": p["snapshot_input"]["created_by_id"],
            "revision_id": entry["revision_id"],
            "revision_sha256": entry["revision_sha256"],
            "snapshot_id": pin["snapshot_id"],
            "snapshot_result_sha256": pin["result_sha256"],
            "card_sha256": entry["card_sha256"],
            "proposal_id": proposal["proposal_id"],
            "proposal_sha256": proposal["sha256"],
            "proposal_contract": proposal["schema"],
            "proposal_receipt_id": entry["proposal_receipt_id"],
            "source_class": proposal["source"]["class"],
            "source_identity": proposal["source"]["identity"],
            "source_digest": proposal["source"]["digest"],
            "original_outcome": proposal["original_outcome"],
            "resolution_effect": "none",
        }.items():
            if event[field] != expected_value:
                raise InvalidReportRenderPayload(
                    "Decision exact proposal binding mismatch"
                )
        if (
            event["owner_statement_only"] is not True
            or event["resolution_verified"] is not False
            or event["source_state_immutable"] is not True
        ):
            raise InvalidReportRenderPayload("Decision cannot resolve original finding")
        if not (
            (
                event["event_kind"] == "disposition"
                and event["state"] in {"act", "defer", "decline", "accept_risk"}
            )
            or (
                event["event_kind"] == "execution"
                and event["state"] in {"completion_recorded", "evidence_reviewed"}
            )
        ):
            raise InvalidReportRenderPayload("Decision state invalid")
        _timestamp(event["created_at"])
        if datetime.fromisoformat(
            event["created_at"].replace("Z", "+00:00")
        ) < datetime.fromisoformat(pin["captured_at"].replace("Z", "+00:00")):
            raise InvalidReportRenderPayload("Decision predates capture")
        if event["previous_event_id"] is not None:
            _uuid(event["previous_event_id"])
        if (event["sequence"] == 1) != (event["previous_event_id"] is None):
            raise InvalidReportRenderPayload("Decision predecessor shape invalid")
        person = event["responsible_label"]
        if (
            type(person) is not str
            or not 1 <= len(person) <= 200
            or person != person.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in person)
            or type(event["notes"]) is not str
            or len(event["notes"]) > 4096
        ):
            raise InvalidReportRenderPayload("Decision owner statement bounds invalid")
        if event["due_date"] is not None and (
            type(event["due_date"]) is not str
            or date.fromisoformat(event["due_date"]).isoformat() != event["due_date"]
        ):
            raise InvalidReportRenderPayload("Decision due date invalid")
        links = event["links"]
        if (
            type(links) is not list
            or len(links) > 10
            or any(
                type(link) is not str
                or len(link) > 2048
                or re.fullmatch(r"https://[^\s/?#@]+([/?#][^\s]*)?", link) is None
                for link in links
            )
        ):
            raise InvalidReportRenderPayload("Decision evidence reference invalid")
    if ordering != sorted(ordering):
        raise InvalidReportRenderPayload("Decision selection ordering invalid")
    return deepcopy(manifest)
