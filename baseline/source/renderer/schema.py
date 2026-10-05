from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

MAX_PAYLOAD_BYTES = 1_048_576
MAX_STRING_LENGTH = 4_096
MAX_COLLECTION_ITEMS = 2_000
MAX_NESTING_DEPTH = 12
REPORT_CONTEXT_VERSION = "AL-REPORT-CONTEXT-2"
REPORT_TITLE = "AI Risk & ROI Assessment"
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
    if set(payload) != REQUIRED_TOP_LEVEL_KEYS:
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

    if payload["context_version"] != REPORT_CONTEXT_VERSION:
        raise InvalidReportRenderPayload("Unsupported report context version")
    if payload["title"] != REPORT_TITLE:
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

    return payload
