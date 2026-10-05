"""Bounded interchange validation. No collection/admission/execution authority.

Error messages are fixed codes: never include provider values or source bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from importlib.metadata import version as installed_version
from pathlib import Path
from uuid import UUID

import rfc8785
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 512 * 1024
MAX_NODES = 10000
MAX_DEPTH = 16
SAFE_INTEGER = 9007199254740991
REQUIRED_FILES = frozenset(
    {
        "__init__.py",
        "contracts.py",
        "adapters.py",
        "openapi-components-v1.json",
        "schemas/assertion-v1.json",
        "schemas/entity-profile-v1.json",
        "schemas/read-payload-v1.json",
        "schemas/read-envelope-v1.json",
        "schemas/normalization-request-v1.json",
    }
)
DEPENDENCIES = {"rfc8785": "0.1.4", "jsonschema": "4.26.0", "referencing": "0.37.0"}
DESCRIPTOR_KEYS = frozenset(
    {
        "id",
        "version",
        "provider",
        "environment",
        "api_version",
        "namespace",
        "subject_kind",
        "pointers",
    }
)
SCHEMA_ID = "urn:stewardence:evidence:read:v1"
PROFILE_ID = "stewardence.entity-descriptor.v1"
UTC_PATTERN = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z"
)


class SemanticContractError(ValueError):
    """A fixed rejection code; it is safe to report without raw evidence."""


def reject(code):
    raise SemanticContractError(code)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            reject("duplicate_json_key")
        result[key] = value
    return result


def _decimal(token):
    if len(token) > 80:
        reject("numeric_token_too_large")
    value = None
    try:
        value = Decimal(token)
    except InvalidOperation:
        pass
    if value is None:
        reject("unsupported_numeric_exponent")
    return value


def _integer(token):
    if len(token) > 80:
        reject("numeric_token_too_large")
    return int(token)


def _constant(_):
    reject("nonfinite_json_number")


def _walk(value, *, source=False):
    pending = [(value, 0)]
    nodes = 0
    allocation_budget = 0
    while pending:
        current, depth = pending.pop()
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            reject("json_resource_bound")
        if type(current) is dict:
            if len(current) * 2 > MAX_NODES:
                reject("json_resource_bound")
            allocation_budget += 2 + 2 * len(current)
            for key, child in current.items():
                if type(key) is not str:
                    reject("invalid_json_key")
                pending.append((key, depth + 1))
                pending.append((child, depth + 1))
        elif type(current) is list:
            if len(current) > MAX_NODES:
                reject("json_resource_bound")
            allocation_budget += 2 + len(current)
            pending.extend((child, depth + 1) for child in current)
        elif type(current) is str:
            # Conservative worst-case escaped UTF-8 budget, BEFORE dumping.
            if not source and len(current) > MAX_BYTES // 6:
                reject("json_byte_bound")
            allocation_budget += 6 * len(current) + 2
            if any(unicodedata.category(c) == "Cs" for c in current):
                reject("invalid_unicode")
        elif type(current) is bool or current is None:
            allocation_budget += 5
        elif type(current) is int:
            allocation_budget += 21
            if not source and abs(current) > SAFE_INTEGER:
                reject("unsafe_json_integer")
        elif source and type(current) is Decimal and current.is_finite():
            continue
        else:
            reject("unsupported_json_type")
        if not source and allocation_budget > MAX_BYTES:
            reject("json_byte_bound")


def parse_json(raw: bytes, *, source=False):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_BYTES:
        reject("json_byte_bound")
    invalid = False
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_decimal,
            parse_int=_integer,
            parse_constant=_constant,
        )
        _walk(value, source=source)
        return value
    except SemanticContractError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        invalid = True
    if invalid:
        # Raise outside the handler: JSONDecodeError retains source .doc.
        reject("invalid_json")


def canonical_bytes(value):
    _walk(value)
    result = None
    try:
        result = rfc8785.dumps(value)
    except (ValueError, UnicodeError):
        pass
    if result is None:
        reject("canonicalization_failed")
    if len(result) > MAX_BYTES:
        reject("json_byte_bound")
    return result


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def utc_text(value: datetime):
    if type(value) is not datetime or value.tzinfo is None or value.utcoffset() is None:
        reject("aware_capture_time_required")
    result = None
    try:
        result = (
            value.astimezone(UTC)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    except (ValueError, OverflowError):
        pass
    if result is None:
        reject("utc_range_invalid")
    return result


def exact_decimal(value: Decimal):
    """No rounding or float conversion; input precision/scale stays separate."""
    if type(value) is not Decimal or not value.is_finite():
        reject("exact_decimal_required")
    # Bound expansion before formatting an attacker-controlled exponent.
    if len(value.as_tuple().digits) > 60 or not -18 <= value.as_tuple().exponent <= 60:
        reject("decimal_precision_bound")
    if not value:
        return "0"
    result = format(value, "f")
    if "." in result:
        result = result.rstrip("0").rstrip(".")
    if len(result) > 80 or sum(c.isdigit() for c in result) > 60:
        reject("decimal_precision_bound")
    return result


def _utc_format(value):
    if not isinstance(value, str) or UTC_PATTERN.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


CHECKER = FormatChecker(formats=["uuid"])
CHECKER.checks("date-time")(_utc_format)


def bundled_contract():
    """Verify immutable local file pins; never dereference a supplied URL."""
    manifest = parse_json((ROOT / "registry-v1.json").read_bytes())
    if type(manifest) is not dict or set(manifest) != {
        "schema",
        "status",
        "writes_enabled",
        "admission_enabled",
        "dependencies",
        "files",
        "artifact_digest",
        "adapters",
    }:
        reject("registry_shape_invalid")
    if (
        manifest["schema"] != "stewardence.semantic-registry.v1"
        or manifest["status"] != "undeployed_candidate"
        or manifest["writes_enabled"] is not False
        or manifest["admission_enabled"] is not False
    ):
        reject("registry_boundary_invalid")
    if type(manifest["files"]) is not dict or set(manifest["files"]) != REQUIRED_FILES:
        reject("registry_inventory_invalid")
    if manifest["dependencies"] != DEPENDENCIES or any(
        installed_version(name) != expected for name, expected in DEPENDENCIES.items()
    ):
        reject("registry_dependency_drift")
    if type(manifest["adapters"]) is not list or len(manifest["adapters"]) != 2:
        reject("registry_adapter_inventory_invalid")
    expected_ids = {
        "quickbooks.sandbox.company-descriptor",
        "microsoft.organization-descriptor",
    }
    seen = set()
    for adapter in manifest["adapters"]:
        if type(adapter) is not dict or set(adapter) != DESCRIPTOR_KEYS | {
            "configuration",
            "mapping_digest",
            "configuration_digest",
        }:
            reject("registry_adapter_shape_invalid")
        if type(adapter["id"]) is not str or adapter["id"] in seen:
            reject("registry_adapter_inventory_invalid")
        seen.add(adapter["id"])
        if adapter["configuration"] != {}:
            reject("unregistered_adapter_configuration")
        descriptor = {key: adapter[key] for key in DESCRIPTOR_KEYS}
        if adapter["mapping_digest"] != digest(descriptor) or adapter[
            "configuration_digest"
        ] != digest(adapter["configuration"]):
            reject("registry_mapping_drift")
    if seen != expected_ids:
        reject("registry_adapter_inventory_invalid")
    artifact = {
        "files": manifest["files"],
        "adapters": manifest["adapters"],
        "dependencies": manifest["dependencies"],
    }
    if manifest["artifact_digest"] != digest(artifact):
        reject("registry_artifact_drift")
    for relative, expected in manifest["files"].items():
        # Registry is operator-bundled configuration, never caller input.
        path = ROOT / relative
        if path.parent not in {ROOT, ROOT / "schemas"} or path.is_symlink():
            reject("registry_path_invalid")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            reject("bundled_contract_drift")
    return manifest


def validate_schema(value, filename):
    manifest = bundled_contract()
    if filename not in {
        "assertion-v1.json",
        "read-payload-v1.json",
        "read-envelope-v1.json",
        "normalization-request-v1.json",
    }:
        reject("unregistered_schema")
    schemas = [
        json.loads((ROOT / "schemas" / name).read_bytes())
        for name in (
            "assertion-v1.json",
            "read-payload-v1.json",
            "read-envelope-v1.json",
            "normalization-request-v1.json",
        )
    ]
    schema = next(
        item
        for item in schemas
        if item["$id"]
        == {
            "assertion-v1.json": "urn:stewardence:evidence:assertion:v1",
            "read-payload-v1.json": SCHEMA_ID,
            "read-envelope-v1.json": "urn:stewardence:evidence:read-envelope:v1",
            "normalization-request-v1.json": "urn:stewardence:evidence:normalization-request:v1",
        }[filename]
    )
    # No remote references are used, and even a future altered schema cannot
    # cause a network lookup through this validator.
    registry = Registry().with_resources(
        (item["$id"], Resource.from_contents(item)) for item in schemas
    )
    validator = Draft202012Validator(schema, format_checker=CHECKER, registry=registry)
    # is_valid returns a decision without raising a ValidationError whose
    # context/instance would retain and expose the rejected provider value.
    if not validator.is_valid(value):
        reject("schema_validation_failed")
    return manifest


def validate_assertion(value):
    _walk(value)
    validate_schema(value, "assertion-v1.json")
    if value["evidence_kind"] in {"observed", "inferred", "calculated"}:
        # A vocabulary entry is not a qualified method/derivation contract.
        # V1 does not admit these bases until a versioned method/input schema
        # exists. The entity profile additionally requires declared values.
        reject("unqualified_evidence_basis")
    typed = value.get("value")
    if typed is not None:
        if typed["type"] in {"integer", "decimal", "money"}:
            numeric = typed.get("data")
            if typed["type"] == "integer" and type(numeric) is not int:
                reject("integer_required")
            if typed["type"] in {"decimal", "money"}:
                number = Decimal(numeric)
                if (
                    exact_decimal(number) != numeric
                    or max(0, -number.as_tuple().exponent) > typed["source_scale"]
                ):
                    reject("decimal_scale_mismatch")
    time = value["effective_time"]
    if time["source_text"] is None and time["utc"] is not None:
        reject("invented_effective_time")
    if time["source_text"] is not None:
        # This v1 subset supports explicit-offset instants with <=6 fractional
        # digits. Date-only/unknown-offset/greater precision is retained without
        # manufacturing a UTC instant. Wider support needs a versioned mapping.
        source = time["source_text"]
        if time["utc"] is None:
            calendar_valid = False
            try:
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", source):
                    date.fromisoformat(source)
                    calendar_valid = True
                elif re.fullmatch(
                    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,18})?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])?",
                    source,
                ):
                    # Parsing checks calendar/offset shape only. It does not
                    # manufacture UTC or alter the retained source precision.
                    datetime.fromisoformat(source.replace("Z", "+00:00"))
                    calendar_valid = True
            except ValueError:
                pass
            if not calendar_valid:
                reject("invalid_effective_time")
        pattern = r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])"
        if time["utc"] is not None:
            if re.fullmatch(pattern, source) is None or source.endswith("-00:00"):
                reject("unresolved_time_offset")
            parsed = None
            try:
                parsed = datetime.fromisoformat(source.replace("Z", "+00:00"))
            except ValueError:
                pass
            if parsed is None:
                reject("invalid_effective_time")
            normalized = utc_text(parsed)
            if normalized != time["utc"]:
                reject("effective_time_mismatch")


@dataclass(frozen=True)
class CaptureContext:
    """Caller-supplied capture binding, not an authenticated receipt or grant."""

    organization_id: UUID
    artifact_receipt_id: UUID
    provider: str
    environment: str
    api_version: str
    account_id: str
    captured_at: datetime

    def __post_init__(self):
        if (
            type(self.organization_id) is not UUID
            or type(self.artifact_receipt_id) is not UUID
        ):
            reject("typed_capture_identity_required")
        if any(
            type(value) is not str
            for value in (
                self.provider,
                self.environment,
                self.api_version,
                self.account_id,
            )
        ):
            reject("typed_capture_labels_required")
        if self.provider not in {"quickbooks_online", "microsoft_365"}:
            reject("unsupported_provider")
        if type(self.account_id) is not str or not 1 <= len(self.account_id) <= 128:
            reject("invalid_account_identity")
        utc_text(self.captured_at)


@dataclass(frozen=True)
class ValidatedReadEvidence:
    """Structure-validated canonical bytes, not authenticated/admitted evidence.

    Python object construction is not an authority boundary. Every live consumer
    must still verify its actual capture, source replay and admission receipt.
    """

    canonical_payload: bytes = field(repr=False)

    def __post_init__(self):
        payload = parse_json(self.canonical_payload)
        validate_schema(payload, "read-payload-v1.json")
        if canonical_bytes(payload) != self.canonical_payload:
            reject("noncanonical_content")

    @property
    def payload_sha256(self):
        return hashlib.sha256(self.canonical_payload).hexdigest()

    def payload(self):
        return json.loads(self.canonical_payload)

    def envelope(self):
        return {
            "algorithm": "sha256-rfc8785",
            "payload_sha256": self.payload_sha256,
            "payload": self.payload(),
        }


def validate_read_envelope(
    raw: bytes,
    *,
    expected_context: CaptureContext,
    expected_raw_sha256: str,
    expected_adapter_id: str,
    expected_adapter_version: str,
):
    """Check exact expected bindings. Caller must separately authenticate them."""
    if type(expected_context) is not CaptureContext:
        reject("typed_capture_context_required")
    value = parse_json(raw)
    manifest = validate_schema(value, "read-envelope-v1.json")
    payload = value["payload"]
    if digest(payload) != value["payload_sha256"]:
        reject("payload_digest_mismatch")
    if payload["schema_digest"] != manifest["files"]["schemas/read-payload-v1.json"]:
        reject("schema_digest_mismatch")
    if (
        payload["semantic_profile_digest"]
        != manifest["files"]["schemas/entity-profile-v1.json"]
    ):
        reject("profile_digest_mismatch")
    source = payload["source"]
    expected = {
        "provider": expected_context.provider,
        "environment": expected_context.environment,
        "api_version": expected_context.api_version,
        "account_id": expected_context.account_id,
        "artifact_receipt_id": str(expected_context.artifact_receipt_id),
        "captured_at": utc_text(expected_context.captured_at),
        "raw_bytes_sha256": expected_raw_sha256,
    }
    if payload["organization_id"] != str(expected_context.organization_id) or any(
        source[key] != item for key, item in expected.items()
    ):
        reject("source_binding_mismatch")
    adapter = next(
        (
            item
            for item in manifest["adapters"]
            if item["id"] == expected_adapter_id
            and item["version"] == expected_adapter_version
        ),
        None,
    )
    if adapter is None:
        reject("unregistered_adapter")
    expected_binding = {
        key: adapter[key]
        for key in ("id", "version", "mapping_digest", "configuration_digest")
    }
    expected_binding["artifact_digest"] = manifest["artifact_digest"]
    if payload["adapter"] != expected_binding:
        reject("adapter_binding_mismatch")
    if any(
        source[key] != adapter[key]
        for key in ("provider", "environment", "api_version")
    ):
        reject("adapter_source_mismatch")
    subject = payload["subject"]
    if (
        subject["namespace"] != adapter["namespace"]
        or subject["kind"] != adapter["subject_kind"]
    ):
        reject("subject_namespace_mismatch")
    profile = json.loads((ROOT / "schemas/entity-profile-v1.json").read_bytes())
    assertions = payload["assertions"]
    concepts = [assertion["concept_id"] for assertion in assertions]
    if concepts != sorted(profile["concepts"]):
        reject("concept_selection_mismatch")
    for assertion in assertions:
        validate_assertion(assertion)
        concept = assertion["concept_id"]
        if assertion["concept_version"] != profile["concepts"][concept]["version"]:
            reject("concept_version_mismatch")
        if assertion["source_pointer"] != adapter["pointers"][concept]:
            reject("source_pointer_mismatch")
        if assertion["evidence_kind"] != "declared" or assertion["value_state"] not in {
            "known",
            "missing",
            "source_null",
        }:
            reject("unsupported_assertion_basis")
        if assertion["effective_time"] != {"source_text": None, "utc": None}:
            reject("unsupported_effective_time")
        if assertion["value_state"] == "known":
            typed = assertion["value"]
            if typed["type"] != profile["concepts"][concept]["type"]:
                reject("concept_type_mismatch")
            if any(
                unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in typed["data"]
            ):
                reject("unsafe_display_text")
    identity = next(a for a in assertions if a["concept_id"] == "entity.provider_id")
    if (
        identity["value_state"] != "known"
        or identity["value"]["data"] != subject["entity_id"]
    ):
        reject("subject_identity_mismatch")
    known = sorted(a["concept_id"] for a in assertions if a["value_state"] == "known")
    if payload["coverage"] != {
        "state": "partial",
        "requested": sorted(profile["concepts"]),
        "covered": known,
        "gaps": ["provider_scope_not_independently_verified"],
    }:
        reject("coverage_claim_mismatch")
    if payload["supersedes"] == value["payload_sha256"]:
        reject("self_supersession")
    return ValidatedReadEvidence(canonical_bytes(payload))
