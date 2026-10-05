from __future__ import annotations

import json
from copy import deepcopy

import pytest

from collector.contract import EvidenceError, digest, validate_bundle
from collector.windows import installed_programs


def example_bundle():
    record = {
        "detector_id": "windows.installed_programs",
        "detector_version": "1",
        "observed_at": "2026-09-05T00:00:00+00:00",
        "evidence_type": "installed_program",
        "evidence_locator": (
            "HKCU/64/SOFTWARE/Microsoft/Windows/CurrentVersion/Uninstall/test"
        ),
        "raw_identifier": "ChatGPT",
        "version": "1",
        "publisher": "OpenAI",
    }
    record["evidence_hash"] = digest(record)
    bundle = {
        "schema_version": 1,
        "collector_version": "0.1.0",
        "device_id": "84814966-f3ad-4d6b-8f6e-927306337267",
        "observed_at": record["observed_at"],
        "coverage": {"windows.installed_programs": "complete"},
        "evidence": [record],
    }
    bundle["scan_id"] = digest(bundle)
    return bundle


def encoded(bundle):
    return json.dumps(bundle).encode()


def test_valid_bundle_and_hash_are_deterministic():
    first = example_bundle()
    assert validate_bundle(encoded(first)) == first
    assert first == example_bundle()


@pytest.mark.parametrize(
    "mutation", ["hash", "schema", "secret", "duplicate", "time", "size", "nested"]
)
def test_bundle_rejects_unsupported_tampered_or_unbounded_input(mutation):
    bundle = deepcopy(example_bundle())
    if mutation == "hash":
        bundle["evidence"][0]["raw_identifier"] = "Tampered"
    if mutation == "schema":
        bundle["schema_version"] = True
    if mutation == "secret":
        bundle["evidence"][0]["password"] = "must-not-be-accepted"
    if mutation == "duplicate":
        bundle["evidence"].append(bundle["evidence"][0])
    if mutation == "time":
        bundle["observed_at"] = "2026-09-05"
    if mutation == "size":
        bundle["evidence"][0]["raw_identifier"] = "x" * 2_000_001
    if mutation == "nested":
        bundle["evidence"][0]["raw_identifier"] = {"unexpected": True}
    with pytest.raises(EvidenceError):
        validate_bundle(encoded(bundle))


def test_duplicate_json_fields_fail_closed():
    with pytest.raises(EvidenceError):
        validate_bundle(b'{"schema_version":1,"schema_version":1}')


def test_unsupported_os_does_not_claim_a_complete_scan(monkeypatch):
    monkeypatch.setattr("collector.windows.sys.platform", "linux")
    assert installed_programs("2026-09-05T00:00:00Z") == ([], "unsupported")
