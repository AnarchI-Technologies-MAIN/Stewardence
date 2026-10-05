"""Pinned offline translations; never fetch, authorize, persist, or write."""

import hashlib
import re
from datetime import datetime
from uuid import UUID

from .contracts import (
    PROFILE_ID,
    SCHEMA_ID,
    CaptureContext,
    bundled_contract,
    canonical_bytes,
    parse_json,
    reject,
    utc_text,
    validate_read_envelope,
    validate_schema,
)


def _assertion(concept, record, key, pointer):
    result = {
        "concept_id": concept,
        "concept_version": 1,
        "evidence_kind": "declared",
        "source_pointer": pointer,
        "effective_time": {"source_text": None, "utc": None},
    }
    if key not in record:
        result.update(value_state="missing", reason="source_property_absent")
    elif record[key] is None:
        result.update(
            value_state="source_null", value=None, reason="source_explicit_null"
        )
    elif type(record[key]) is str:
        result.update(value_state="known", value={"type": "text", "data": record[key]})
    else:
        reject("unsupported_provider_field_type")
    return result


def normalize_read(
    raw: bytes,
    context: CaptureContext,
    *,
    adapter_id: str,
    adapter_version: str,
    supersedes: str | None = None,
):
    """Pure translation of a supplied bounded response, not live integration."""
    if type(context) is not CaptureContext:
        reject("typed_capture_context_required")
    manifest = bundled_contract()
    adapter = next(
        (
            item
            for item in manifest["adapters"]
            if item["id"] == adapter_id and item["version"] == adapter_version
        ),
        None,
    )
    if adapter is None:
        reject("unregistered_adapter")
    if any(
        getattr(context, key) != adapter[key]
        for key in ("provider", "environment", "api_version")
    ):
        reject("adapter_source_mismatch")
    source = parse_json(raw, source=True)
    if type(source) is not dict:
        reject("provider_object_required")
    if adapter_id == "quickbooks.sandbox.company-descriptor":
        if (
            re.fullmatch(r"[0-9]{1,32}", context.account_id) is None
            or "Fault" in source
        ):
            reject("invalid_provider_account")
        record = source.get("CompanyInfo")
        identity_key, name_key = "Id", "CompanyName"
        if (
            type(record) is not dict
            or type(record.get(identity_key)) is not str
            or re.fullmatch(r"[0-9]{1,32}", record[identity_key]) is None
        ):
            reject("invalid_provider_entity")
        # CompanyInfo.Id identifies an object, not the realm/account. The
        # authenticated capture must establish the actual realm independently.
    elif adapter_id == "microsoft.organization-descriptor":
        rows = source.get("value")
        if (
            "error" in source
            or "@odata.nextLink" in source
            or type(rows) is not list
            or len(rows) != 1
            or type(rows[0]) is not dict
        ):
            reject("invalid_provider_entity")
        record = rows[0]
        identity_key, name_key = "id", "displayName"
        identity = record.get(identity_key)
        if (
            type(identity) is not str
            or re.fullmatch(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                identity,
            )
            is None
        ):
            reject("invalid_provider_entity")
        if identity != record[identity_key] or identity != context.account_id:
            reject("provider_account_mismatch")
    else:
        reject("unregistered_adapter")
    assertions = [
        _assertion(
            "entity.display_name",
            record,
            name_key,
            adapter["pointers"]["entity.display_name"],
        ),
        _assertion(
            "entity.provider_id",
            record,
            identity_key,
            adapter["pointers"]["entity.provider_id"],
        ),
    ]
    payload = {
        "schema_id": SCHEMA_ID,
        "schema_digest": manifest["files"]["schemas/read-payload-v1.json"],
        "semantic_profile_id": PROFILE_ID,
        "semantic_profile_digest": manifest["files"]["schemas/entity-profile-v1.json"],
        "organization_id": str(context.organization_id),
        "source": {
            "provider": context.provider,
            "environment": context.environment,
            "api_version": context.api_version,
            "account_id": context.account_id,
            "artifact_receipt_id": str(context.artifact_receipt_id),
            "raw_bytes_sha256": hashlib.sha256(raw).hexdigest(),
            "captured_at": utc_text(context.captured_at),
            "media_type": "application/json",
        },
        "adapter": {
            "id": adapter_id,
            "version": adapter_version,
            "artifact_digest": manifest["artifact_digest"],
            "mapping_digest": adapter["mapping_digest"],
            "configuration_digest": adapter["configuration_digest"],
        },
        "subject": {
            "namespace": adapter["namespace"],
            "entity_id": record[identity_key],
            "kind": adapter["subject_kind"],
        },
        "assertions": assertions,
        "coverage": {
            "state": "partial",
            "requested": sorted(a["concept_id"] for a in assertions),
            "covered": sorted(
                a["concept_id"] for a in assertions if a["value_state"] == "known"
            ),
            "gaps": ["provider_scope_not_independently_verified"],
        },
        "supersedes": supersedes,
    }
    canonical = canonical_bytes(payload)
    envelope = {
        "algorithm": "sha256-rfc8785",
        "payload_sha256": hashlib.sha256(canonical).hexdigest(),
        "payload": payload,
    }
    return validate_read_envelope(
        canonical_bytes(envelope),
        expected_context=context,
        expected_raw_sha256=payload["source"]["raw_bytes_sha256"],
        expected_adapter_id=adapter_id,
        expected_adapter_version=adapter_version,
    )


def verify_read_translation(
    envelope_raw: bytes,
    source_raw: bytes,
    context: CaptureContext,
    *,
    adapter_id: str,
    adapter_version: str,
):
    """Re-derive content from exact source bytes, beyond self-consistent hashes.

    This still cannot authenticate the capture or admit a database receipt.
    """
    # Apply type/byte/structure limits before computing the source digest.
    parse_json(source_raw, source=True)
    result = validate_read_envelope(
        envelope_raw,
        expected_context=context,
        expected_raw_sha256=hashlib.sha256(source_raw).hexdigest(),
        expected_adapter_id=adapter_id,
        expected_adapter_version=adapter_version,
    )
    expected = normalize_read(
        source_raw,
        context,
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        supersedes=result.payload()["supersedes"],
    )
    if expected.canonical_payload != result.canonical_payload:
        reject("translation_replay_mismatch")
    return result


def prepare_read_request(
    source_raw: bytes,
    context: CaptureContext,
    *,
    adapter_id: str,
    adapter_version: str,
    supersedes: str | None = None,
):
    """Create a pinned language-agnostic request at preparation time.

    This is a shape-valid capture request, not an issued job or authority grant.
    Callers authenticate capture/receipt and persist the exact request separately.
    """
    if type(context) is not CaptureContext:
        reject("typed_capture_context_required")
    parse_json(source_raw, source=True)
    manifest = bundled_contract()
    adapter = next(
        (
            item
            for item in manifest["adapters"]
            if item["id"] == adapter_id and item["version"] == adapter_version
        ),
        None,
    )
    if adapter is None:
        reject("unregistered_adapter")
    if any(
        getattr(context, key) != adapter[key]
        for key in ("provider", "environment", "api_version")
    ):
        reject("adapter_source_mismatch")
    request = {
        "schema_id": "urn:stewardence:evidence:normalization-request:v1",
        "request_schema_digest": manifest["files"][
            "schemas/normalization-request-v1.json"
        ],
        "organization_id": str(context.organization_id),
        "target_schema_id": SCHEMA_ID,
        "target_schema_digest": manifest["files"]["schemas/read-payload-v1.json"],
        "semantic_profile_id": PROFILE_ID,
        "semantic_profile_digest": manifest["files"]["schemas/entity-profile-v1.json"],
        "source": {
            "provider": context.provider,
            "environment": context.environment,
            "api_version": context.api_version,
            "account_id": context.account_id,
            "artifact_receipt_id": str(context.artifact_receipt_id),
            "raw_bytes_sha256": hashlib.sha256(source_raw).hexdigest(),
            "captured_at": utc_text(context.captured_at),
            "media_type": "application/json",
        },
        "adapter": {
            "id": adapter_id,
            "version": adapter_version,
            "artifact_digest": manifest["artifact_digest"],
            "mapping_digest": adapter["mapping_digest"],
            "configuration_digest": adapter["configuration_digest"],
        },
        "supersedes": supersedes,
    }
    validate_schema(request, "normalization-request-v1.json")
    return canonical_bytes(request)


def normalize_request(request_raw: bytes, source_raw: bytes):
    """Normalized wire entrypoint. Exact interpretation pins must still match.

    No HTTP route, broker, persistence or write executor is attached to it.
    Its caller must verify authority and capture binding before live admission.
    """
    request = parse_json(request_raw)
    manifest = validate_schema(request, "normalization-request-v1.json")
    parse_json(source_raw, source=True)
    if request["source"]["raw_bytes_sha256"] != hashlib.sha256(source_raw).hexdigest():
        reject("source_binding_mismatch")
    expected = {
        "request_schema_digest": manifest["files"][
            "schemas/normalization-request-v1.json"
        ],
        "target_schema_digest": manifest["files"]["schemas/read-payload-v1.json"],
        "semantic_profile_digest": manifest["files"]["schemas/entity-profile-v1.json"],
    }
    if (
        any(request[key] != value for key, value in expected.items())
        or request["adapter"]["artifact_digest"] != manifest["artifact_digest"]
    ):
        reject("normalization_pin_mismatch")
    source = request["source"]
    context = CaptureContext(
        UUID(request["organization_id"]),
        UUID(source["artifact_receipt_id"]),
        source["provider"],
        source["environment"],
        source["api_version"],
        source["account_id"],
        datetime.fromisoformat(source["captured_at"].replace("Z", "+00:00")),
    )
    result = normalize_read(
        source_raw,
        context,
        adapter_id=request["adapter"]["id"],
        adapter_version=request["adapter"]["version"],
        supersedes=request["supersedes"],
    )
    if result.payload()["adapter"] != request["adapter"]:
        reject("normalization_pin_mismatch")
    return result
