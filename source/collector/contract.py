from __future__ import annotations

import hashlib
import json
from datetime import datetime
from uuid import UUID

import rfc8785

SCHEMA_VERSION = 1
COLLECTOR_VERSION = "0.1.0"
MAX_BUNDLE_BYTES = 2_000_000
MAX_EVIDENCE = 2000
DETECTOR_ID = "windows.installed_programs"
DETECTOR_VERSION = "1"
RECORD_FIELDS = {
    "detector_id",
    "detector_version",
    "observed_at",
    "evidence_type",
    "evidence_locator",
    "raw_identifier",
    "version",
    "publisher",
    "evidence_hash",
}


class EvidenceError(ValueError):
    pass


def digest(value) -> str:
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        raise EvidenceError("Invalid observation time")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise EvidenceError("Invalid observation time") from error
    if parsed.utcoffset() is None:
        raise EvidenceError("Observation time requires a timezone")
    return parsed


def fingerprint(record) -> str:
    return digest(
        {
            key: record[key]
            for key in (
                "detector_id",
                "evidence_type",
                "evidence_locator",
                "raw_identifier",
            )
        }
    )


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError("Duplicate JSON field")
        result[key] = value
    return result


def validate_bundle(raw: bytes) -> dict:
    if len(raw) > MAX_BUNDLE_BYTES:
        raise EvidenceError("Evidence bundle exceeds the size limit")
    try:
        bundle = json.loads(raw, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise EvidenceError("Invalid evidence JSON") from error
    fields = {
        "schema_version",
        "collector_version",
        "device_id",
        "observed_at",
        "coverage",
        "evidence",
        "scan_id",
    }
    if not isinstance(bundle, dict) or set(bundle) != fields:
        raise EvidenceError("Unsupported bundle fields")
    if type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1:
        raise EvidenceError("Unsupported schema version")
    if bundle["collector_version"] != COLLECTOR_VERSION:
        raise EvidenceError("Unsupported Collector version")
    try:
        if str(UUID(bundle["device_id"])) != bundle["device_id"]:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as error:
        raise EvidenceError("Invalid device identity") from error
    timestamp(bundle["observed_at"])
    coverage = bundle["coverage"]
    if not isinstance(coverage, dict) or set(coverage) != {DETECTOR_ID}:
        raise EvidenceError("Unsupported detector coverage")
    if coverage[DETECTOR_ID] not in ("complete", "partial", "unsupported"):
        raise EvidenceError("Invalid detector coverage")
    records = bundle["evidence"]
    if not isinstance(records, list) or len(records) > MAX_EVIDENCE:
        raise EvidenceError("Too many evidence records")
    seen = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
            raise EvidenceError("Unsupported evidence fields")
        for value in record.values():
            if not isinstance(value, str) or len(value) > 512:
                raise EvidenceError("Evidence fields must be bounded text")
            if any(ord(character) < 32 for character in value):
                raise EvidenceError("Control characters are not permitted")
        if (
            record["detector_id"] != DETECTOR_ID
            or record["detector_version"] != DETECTOR_VERSION
            or record["evidence_type"] != "installed_program"
        ):
            raise EvidenceError("Unsupported detector or evidence type")
        if record["observed_at"] != bundle["observed_at"]:
            raise EvidenceError("Inconsistent observation time")
        if not record["raw_identifier"].strip():
            raise EvidenceError("A product identifier is required")
        if not record["evidence_locator"].startswith(("HKLM/", "HKCU/")):
            raise EvidenceError("Unsupported registry source")
        expected = digest({k: v for k, v in record.items() if k != "evidence_hash"})
        if record["evidence_hash"] != expected:
            raise EvidenceError("Evidence hash mismatch")
        identity = fingerprint(record)
        if identity in seen:
            raise EvidenceError("Duplicate source observation")
        seen.add(identity)
    if coverage[DETECTOR_ID] == "unsupported" and records:
        raise EvidenceError("Unsupported coverage cannot contain observations")
    expected = digest({k: v for k, v in bundle.items() if k != "scan_id"})
    if bundle["scan_id"] != expected:
        raise EvidenceError("Bundle hash mismatch")
    return bundle
