from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

import rfc8785

MAX_PAYLOAD_BYTES = 1_048_576
MAX_STRING_LENGTH = 4_096
MAX_COLLECTION_ITEMS = 2_000
MAX_NESTING_DEPTH = 12
REPORT_CONTEXT_VERSION = "AL-REPORT-CONTEXT-2"
REPORT_TITLE = "AI Risk & ROI Assessment"
REVIEW_CONTEXT_VERSION = "AL-REVIEW-PACK-CONTEXT-1"
REVIEW_TITLE = "Frozen AI Evidence Review Pack"
REPORT_IDENTIFIER = re.compile(r"^AL-\d{4}-\d{6,}$")

REQUIRED_TOP_LEVEL_KEYS = frozenset(
    {
        "context_version",
        "title",
        "metadata",
        "executive_summary",
        "inventory",
        "risk_overview",
        "individual_risk_findings",
        "policy_findings",
        "recommendations",
        "ai_expenditure",
        "roi",
        "methodology",
        "evidence",
        "assessment_date",
        "ruleset_versions",
    }
)
FORBIDDEN_KEYS = frozenset(
    {
        "css",
        "file",
        "filesystem_path",
        "html",
        "href",
        "javascript",
        "output_path",
        "path",
        "script",
        "src",
        "url",
    }
)


class InvalidReportRenderPayload(ValueError):
    pass


def _validate_tree(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_NESTING_DEPTH:
        raise InvalidReportRenderPayload("Payload nesting is too deep")
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise InvalidReportRenderPayload("Payload string is too long")
        if "\x00" in value:
            raise InvalidReportRenderPayload("Payload strings cannot contain NUL")
        return
    if isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise InvalidReportRenderPayload("Payload collection is too large")
        for item in value:
            _validate_tree(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise InvalidReportRenderPayload("Payload collection is too large")
        for key, item in value.items():
            if not isinstance(key, str):
                raise InvalidReportRenderPayload("Payload keys must be strings")
            if key.casefold() in FORBIDDEN_KEYS:
                raise InvalidReportRenderPayload(f"Forbidden payload field: {key}")
            _validate_tree(item, depth=depth + 1)
        return
    raise InvalidReportRenderPayload("Payload contains an unsupported value type")


def _require_mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise InvalidReportRenderPayload(f"{key} must be an object")
    return value


def _require_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise InvalidReportRenderPayload(f"{key} must be an array")
    return value


def validate_report_render_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InvalidReportRenderPayload("Payload must be an object")
    if payload.get("context_version") == "AL-REVIEW-PACK-CONTEXT-3":
        from .capture_pack_v4_schema import validate_capture_v4_render_payload

        return validate_capture_v4_render_payload(payload)
    if payload.get("context_version") == "AL-REVIEW-PACK-CONTEXT-2":
        from .capture_schema import validate_capture_render_payload

        return validate_capture_render_payload(payload)
    is_review = payload.get("context_version") == REVIEW_CONTEXT_VERSION
    expected_keys = (
        REQUIRED_TOP_LEVEL_KEYS | {"review_pack"}
        if is_review
        else REQUIRED_TOP_LEVEL_KEYS
    )
    if set(payload) != expected_keys:
        raise InvalidReportRenderPayload(
            "Payload fields do not match the report schema"
        )

    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise InvalidReportRenderPayload("Payload is not strict JSON") from error
    if len(encoded) > MAX_PAYLOAD_BYTES:
        raise InvalidReportRenderPayload("Payload is too large")
    _validate_tree(payload)

    if payload["context_version"] not in (
        REPORT_CONTEXT_VERSION,
        REVIEW_CONTEXT_VERSION,
    ):
        raise InvalidReportRenderPayload("Unsupported report context version")
    if payload["title"] != (REVIEW_TITLE if is_review else REPORT_TITLE):
        raise InvalidReportRenderPayload("Unsupported report title")

    metadata = _require_mapping(payload, "metadata")
    required_metadata = {
        "report_identifier",
        "organization_display_name",
        "assessment_date",
        "assessment_id",
        "assessment_version",
        "assessment_snapshot_id",
        "input_sha256",
        "result_sha256",
    }
    if set(metadata) != required_metadata:
        raise InvalidReportRenderPayload("Metadata fields do not match the schema")
    if not REPORT_IDENTIFIER.fullmatch(metadata["report_identifier"]):
        raise InvalidReportRenderPayload("Report identifier is invalid")
    for field in ("assessment_id", "assessment_snapshot_id"):
        try:
            UUID(metadata[field])
        except (AttributeError, TypeError, ValueError) as error:
            raise InvalidReportRenderPayload(f"{field} must be a UUID") from error
    for field in ("input_sha256", "result_sha256"):
        value = metadata[field]
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise InvalidReportRenderPayload(f"{field} must be a SHA-256 digest")

    for key in (
        "executive_summary",
        "risk_overview",
        "ai_expenditure",
        "roi",
        "methodology",
        "ruleset_versions",
    ):
        _require_mapping(payload, key)
    for key in (
        "inventory",
        "individual_risk_findings",
        "policy_findings",
        "recommendations",
        "evidence",
    ):
        _require_list(payload, key)

    if is_review:
        _validate_review_pack(payload)
    return payload


def _closed(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise InvalidReportRenderPayload("Review fields do not match the closed schema")


def _digest(value):
    try:
        return hashlib.sha256(rfc8785.dumps(value)).hexdigest()
    except (TypeError, ValueError) as error:
        raise InvalidReportRenderPayload(
            "Review value is not canonical JSON"
        ) from error


def _uuid(value):
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError()
    except (TypeError, ValueError, AttributeError) as error:
        raise InvalidReportRenderPayload(
            "Review identity is not a canonical UUID"
        ) from error


def _sha(value):
    if type(value) is not str or not re.fullmatch("[0-9a-f]{64}", value):
        raise InvalidReportRenderPayload("Review digest is invalid")


def _timestamp(value):
    from datetime import datetime

    try:
        if type(value) is not str or datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError()
    except (TypeError, ValueError) as error:
        raise InvalidReportRenderPayload(
            "Review timestamp must include a timezone"
        ) from error


def _validate_review_pack(report):
    """Check render-contract consistency; origin admission remains upstream."""
    pack = report["review_pack"]
    _closed(
        pack,
        (
            "schema",
            "pack_id",
            "manifest_sha256",
            "manifest",
            "selected_decisions",
            "exposure_reviews",
        ),
    )
    if pack["schema"] != "stewardence.review_pack_render.v1":
        raise InvalidReportRenderPayload("Unsupported review render schema")
    _uuid(pack["pack_id"])
    _sha(pack["manifest_sha256"])
    manifest = pack["manifest"]
    _closed(
        manifest,
        (
            "schema",
            "cycle_id",
            "organization_id",
            "baseline_pack_id",
            "snapshot",
            "selected_decisions",
            "selection_scope",
            "artifact_state",
            "baseline_promotion",
        ),
    )
    if (
        manifest["schema"] != "stewardence.review_pack.v2"
        or _digest(manifest) != pack["manifest_sha256"]
    ):
        raise InvalidReportRenderPayload("Frozen manifest digest mismatch")
    _uuid(manifest["cycle_id"])
    _uuid(manifest["organization_id"])
    if manifest["baseline_pack_id"] is not None:
        _uuid(manifest["baseline_pack_id"])
    if (
        manifest["selection_scope"]
        not in ("empty_initial_kernel", "owner_statement_events")
        or manifest["artifact_state"] != "not_created"
        or manifest["baseline_promotion"] != "blocked"
    ):
        raise InvalidReportRenderPayload("Unsupported frozen manifest meaning")
    snapshot = manifest["snapshot"]
    _closed(
        snapshot,
        (
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
        ),
    )
    for field in ("snapshot_id", "assessment_id", "workflow_profile_id"):
        _uuid(snapshot[field])
    for field in (
        "input_sha256",
        "result_sha256",
        "workflow_settings_sha256",
        "rules_sha256",
        "configuration_sha256",
    ):
        _sha(snapshot[field])
    metadata = report["metadata"]
    if (
        report["assessment_date"] != snapshot["captured_at"]
        or report["methodology"].get("engine_versions") != snapshot["engine_versions"]
    ):
        raise InvalidReportRenderPayload("Review assessment meaning mismatch")
    for field, target in (
        ("snapshot_id", "assessment_snapshot_id"),
        ("assessment_id", "assessment_id"),
        ("assessment_version", "assessment_version"),
        ("input_sha256", "input_sha256"),
        ("result_sha256", "result_sha256"),
        ("captured_at", "assessment_date"),
    ):
        if snapshot[field] != metadata[target]:
            raise InvalidReportRenderPayload("Review snapshot metadata mismatch")
    _timestamp(snapshot["captured_at"])
    if (
        type(snapshot["assessment_version"]) is not int
        or snapshot["assessment_version"] < 1
        or type(snapshot["snapshot_schema"]) is not int
        or snapshot["snapshot_schema"] != 1
        or snapshot["workflow_profile"] not in ("business.v1", "development.v1")
        or type(snapshot["engine_versions"]) is not dict
    ):
        raise InvalidReportRenderPayload("Unsupported frozen snapshot meaning")
    if (
        type(pack["selected_decisions"]) is not list
        or type(manifest["selected_decisions"]) is not list
    ):
        raise InvalidReportRenderPayload("Review decisions must be arrays")
    if [
        item.get("selection") if type(item) is dict else None
        for item in pack["selected_decisions"]
    ] != manifest["selected_decisions"]:
        raise InvalidReportRenderPayload("Frozen decision selection changed")
    if (
        manifest["selection_scope"] == "empty_initial_kernel"
        and manifest["selected_decisions"]
    ):
        raise InvalidReportRenderPayload("Empty selection scope contains decisions")
    seen = set()
    for entry in pack["selected_decisions"]:
        _closed(entry, ("selection", "payload", "event_sha256", "proposal"))
        selection = entry["selection"]
        event = entry["payload"]
        proposal = entry["proposal"]
        _closed(
            selection,
            (
                "event_id",
                "event_sha256",
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
            ),
        )
        _closed(
            event,
            (
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
            ),
        )
        _closed(
            proposal,
            (
                "inventory_item_id",
                "rule_id",
                "rule_version",
                "severity",
                "proposal",
                "authority",
            ),
        )
        if (
            event["schema"] != "stewardence.core_decision_event.v1"
            or proposal["authority"] != "proposal_only"
        ):
            raise InvalidReportRenderPayload("Unsupported proposal or event authority")
        _uuid(proposal["inventory_item_id"])
        if any(
            type(proposal[field]) is not str
            for field in ("rule_id", "rule_version", "severity", "proposal")
        ):
            raise InvalidReportRenderPayload("Proposal display fields must be text")
        _timestamp(event["created_at"])
        for field in (
            "id",
            "organization_id",
            "created_by_id",
            "revision_id",
            "snapshot_id",
        ):
            _uuid(event[field])
        if event["previous_event_id"] is not None:
            _uuid(event["previous_event_id"])
        if (
            entry["event_sha256"] != selection["event_sha256"]
            or _digest(event) != entry["event_sha256"]
            or _digest(proposal) != selection["card_sha256"]
        ):
            raise InvalidReportRenderPayload(
                "Selected event or proposal digest mismatch"
            )
        for field in ("revision_sha256", "card_sha256", "snapshot_result_sha256"):
            _sha(event[field])
        for field in (
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
        ):
            if event[field] != selection[field]:
                raise InvalidReportRenderPayload("Selected event identity mismatch")
        if (
            event["id"] != selection["event_id"]
            or event["organization_id"] != manifest["organization_id"]
            or event["snapshot_id"] != snapshot["snapshot_id"]
            or event["snapshot_result_sha256"] != snapshot["result_sha256"]
        ):
            raise InvalidReportRenderPayload("Selected event snapshot mismatch")
        if (
            type(event["card_index"]) is not int
            or event["card_index"] < 0
            or type(event["sequence"]) is not int
            or event["sequence"] < 1
            or event["owner_statement_only"] is not True
            or event["resolution_verified"] is not False
        ):
            raise InvalidReportRenderPayload("Invalid owner-statement semantics")
        key = (event["revision_id"], event["card_index"])
        if key in seen:
            raise InvalidReportRenderPayload("Duplicate selected proposal")
        seen.add(key)
        if type(event["event_kind"]) is not str or type(event["state"]) is not str:
            raise InvalidReportRenderPayload("Decision state must be text")
        if (event["event_kind"], event["state"]) not in {
            ("disposition", "act"),
            ("disposition", "defer"),
            ("disposition", "decline"),
            ("disposition", "accept_risk"),
            ("execution", "completion_recorded"),
            ("execution", "evidence_reviewed"),
        }:
            raise InvalidReportRenderPayload("Unsupported decision state")
        if (
            type(event["responsible_label"]) is not str
            or not 1 <= len(event["responsible_label"].strip()) <= 200
            or type(event["notes"]) is not str
            or type(event["links"]) is not list
            or len(event["links"]) > 10
        ):
            raise InvalidReportRenderPayload("Invalid statement bounds")
        if event["due_date"] is not None:
            from datetime import date

            try:
                date.fromisoformat(event["due_date"])
            except (TypeError, ValueError) as error:
                raise InvalidReportRenderPayload("Invalid decision due date") from error
        for link in event["links"]:
            if (
                type(link) is not str
                or len(link) > 2048
                or not re.fullmatch(r"https://[^\s/?#@]+(?:[/?#][^\s]*)?", link)
            ):
                raise InvalidReportRenderPayload("Invalid evidence link")
    if type(pack["exposure_reviews"]) is not list:
        raise InvalidReportRenderPayload("Exposure reviews must be an array")
    if any(type(item) is not dict or "id" not in item for item in report["inventory"]):
        raise InvalidReportRenderPayload("Invalid review inventory record")
    inventory_ids = [item["id"] for item in report["inventory"]]
    for identity in inventory_ids:
        _uuid(identity)
    if len(set(inventory_ids)) != len(inventory_ids):
        raise InvalidReportRenderPayload("Duplicate review inventory identity")
    for entry in pack["selected_decisions"]:
        if entry["proposal"]["inventory_item_id"] not in inventory_ids:
            raise InvalidReportRenderPayload("Selected proposal inventory mismatch")
    if any(type(item) is not dict for item in pack["exposure_reviews"]):
        raise InvalidReportRenderPayload("Invalid exposure entry")
    for item in pack["exposure_reviews"]:
        _closed(item, ("source_record", "review"))
    if any(
        type(item["review"]) is not dict or type(item["source_record"]) is not dict
        for item in pack["exposure_reviews"]
    ):
        raise InvalidReportRenderPayload("Invalid exposure record")
    if [
        item["review"].get("inventory_item_id") for item in pack["exposure_reviews"]
    ] != inventory_ids:
        raise InvalidReportRenderPayload("Exposure inventory selection mismatch")
    question_ids = (
        "business_owner",
        "business_purpose",
        "data_categories",
        "permissions",
        "capabilities",
        "approval",
        "account_identity",
        "access_removal",
    )
    for entry in pack["exposure_reviews"]:
        exposure = entry["review"]
        record = entry["source_record"]
        _closed(
            exposure,
            (
                "schema",
                "inventory_item_id",
                "record_sha256",
                "questions",
                "authority",
                "verification",
                "sha256",
            ),
        )
        _uuid(exposure["inventory_item_id"])
        _sha(exposure["record_sha256"])
        if (
            record.get("id") != exposure["inventory_item_id"]
            or _digest(record) != exposure["record_sha256"]
        ):
            raise InvalidReportRenderPayload("Exposure source-record digest mismatch")
        if (
            exposure["schema"] != "core.exposure.declarations.v1"
            or exposure["authority"] != "proposal_only"
            or exposure["verification"] != "not_established"
            or _digest(
                {key: value for key, value in exposure.items() if key != "sha256"}
            )
            != exposure["sha256"]
        ):
            raise InvalidReportRenderPayload("Exposure contract or digest mismatch")
        if (
            type(exposure["questions"]) is not list
            or any(type(q) is not dict for q in exposure["questions"])
            or [q.get("question_id") for q in exposure["questions"]]
            != list(question_ids)
        ):
            raise InvalidReportRenderPayload("Exposure questions incomplete")
        for question in exposure["questions"]:
            _closed(
                question,
                (
                    "question_id",
                    "outcome",
                    "explanation",
                    "source_fields",
                    "basis",
                    "verification",
                ),
            )
            if (
                question["outcome"]
                not in ("PASS", "CONCERN", "UNKNOWN", "NOT_APPLICABLE")
                or question["basis"]
                != (
                    "unknown"
                    if question["outcome"] == "UNKNOWN"
                    else "customer_declaration"
                )
                or question["verification"] != "not_established"
                or type(question["explanation"]) is not str
                or type(question["source_fields"]) is not list
                or any(type(field) is not str for field in question["source_fields"])
            ):
                raise InvalidReportRenderPayload("Unsupported exposure meaning")
