"""Adversarial offline semantic tests; no provider, database or write calls."""

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from jsonschema import Draft202012Validator

from apps.integrations.semantics.adapters import (
    normalize_read,
    normalize_request,
    prepare_read_request,
    verify_read_translation,
)
from apps.integrations.semantics.contracts import (
    MAX_BYTES,
    CaptureContext,
    SemanticContractError,
    ValidatedReadEvidence,
    bundled_contract,
    canonical_bytes,
    digest,
    exact_decimal,
    parse_json,
    validate_assertion,
    validate_read_envelope,
)

QBO_ADAPTER = "quickbooks.sandbox.company-descriptor"
MS_ADAPTER = "microsoft.organization-descriptor"
SOURCE = b'{"CompanyInfo":{"Id":"1","CompanyName":"Synthetic Firm","uninterpreted":"preserved only in source"}}'


def context(provider="quickbooks_online"):
    return CaptureContext(
        UUID("11111111-1111-4111-8111-111111111111"),
        UUID("22222222-2222-4222-8222-222222222222"),
        provider,
        "sandbox" if provider == "quickbooks_online" else "owner_preview",
        "v3" if provider == "quickbooks_online" else "graph.v1.0",
        "12345"
        if provider == "quickbooks_online"
        else "33333333-3333-4333-8333-333333333333",
        datetime(2026, 10, 3, 12, 30, tzinfo=timezone(timedelta(hours=-5))),
    )


def qbo(raw=SOURCE, ctx=None):
    return normalize_read(
        raw, ctx or context(), adapter_id=QBO_ADAPTER, adapter_version="1.0.0"
    )


def validate(envelope, ctx=None, **kwargs):
    return validate_read_envelope(
        canonical_bytes(envelope),
        expected_context=ctx or context(),
        expected_raw_sha256=hashlib.sha256(SOURCE).hexdigest(),
        expected_adapter_id=kwargs.get("adapter_id", QBO_ADAPTER),
        expected_adapter_version=kwargs.get("adapter_version", "1.0.0"),
    )


def rehash(envelope):
    envelope["payload_sha256"] = digest(envelope["payload"])
    return envelope


def assertion(state="known", value=None):
    result = {
        "concept_id": "fixture.measurement",
        "concept_version": 1,
        "evidence_kind": "declared",
        "value_state": state,
        "source_pointer": "/field",
        "effective_time": {"source_text": None, "utc": None},
    }
    if state == "known":
        result["value"] = value or {"type": "text", "data": ""}
    elif state == "source_null":
        result.update(value=None, reason="source_explicit_null")
    else:
        result["reason"] = "source_property_absent"
    return result


def test_bundled_schemas_are_valid_202012_and_integrity_pinned():
    manifest = bundled_contract()
    assert manifest["writes_enabled"] is False
    assert manifest["admission_enabled"] is False
    root = Path(__file__).resolve().parents[1] / "apps/integrations/semantics/schemas"
    for name in (
        "assertion-v1.json",
        "read-payload-v1.json",
        "read-envelope-v1.json",
        "normalization-request-v1.json",
    ):
        Draft202012Validator.check_schema(json.loads((root / name).read_bytes()))


def test_two_provider_models_use_same_concepts_without_equating_subjects():
    first = qbo().payload()
    ctx = context("microsoft_365")
    raw = json.dumps(
        {"value": [{"id": ctx.account_id, "displayName": "Synthetic Firm"}]}
    ).encode()
    second = normalize_read(
        raw, ctx, adapter_id=MS_ADAPTER, adapter_version="1.0.0"
    ).payload()
    assert [a["concept_id"] for a in first["assertions"]] == [
        a["concept_id"] for a in second["assertions"]
    ]
    assert first["assertions"][0]["value"] == second["assertions"][0]["value"]
    assert first["subject"]["namespace"] != second["subject"]["namespace"]
    assert first["subject"]["kind"] != second["subject"]["kind"]
    assert first["source"]["captured_at"] == "2026-10-03T17:30:00.000000Z"
    assert first["assertions"][0]["evidence_kind"] == "declared"
    assert first["assertions"][0]["effective_time"] == {
        "source_text": None,
        "utc": None,
    }
    assert first["source"]["account_id"] == "12345"
    assert first["subject"]["entity_id"] == "1"  # CompanyInfo.Id is not realm.


@pytest.mark.parametrize(
    "fragment,state,value",
    [
        ("", "missing", None),
        (',"CompanyName":null', "source_null", None),
        (',"CompanyName":""', "known", ""),
    ],
)
def test_provider_missing_null_and_empty_are_distinct(fragment, state, value):
    raw = ('{"CompanyInfo":{"Id":"1"' + fragment + "}}").encode()
    item = qbo(raw).payload()["assertions"][0]
    assert item["value_state"] == state
    if state == "missing":
        assert "value" not in item
    elif state == "source_null":
        assert item["value"] is None
    else:
        assert item["value"]["data"] == value


def test_existing_microsoft_id_only_collection_remains_missing_name():
    ctx = context("microsoft_365")
    result = normalize_read(
        json.dumps({"value": [{"id": ctx.account_id}]}).encode(),
        ctx,
        adapter_id=MS_ADAPTER,
        adapter_version="1.0.0",
    )
    assert result.payload()["assertions"][0]["value_state"] == "missing"


def test_replay_immutable_views_and_no_current_clock_dependency():
    first = qbo()
    second = qbo()
    assert first.canonical_payload == second.canonical_payload
    assert first.payload_sha256 == second.payload_sha256
    view = first.payload()
    view["assertions"][0]["value"]["data"] = "Altered"
    assert first.payload()["assertions"][0]["value"]["data"] == "Synthetic Firm"
    assert "uninterpreted" not in first.canonical_payload.decode()
    assert (
        verify_read_translation(
            canonical_bytes(first.envelope()),
            SOURCE,
            context(),
            adapter_id=QBO_ADAPTER,
            adapter_version="1.0.0",
        )
        == first
    )


def test_self_consistent_counterfeit_value_requires_exact_source_replay():
    envelope = qbo().envelope()
    envelope["payload"]["assertions"][0]["value"]["data"] = "Fabricated Firm"
    rehash(envelope)
    # Structural validation is deliberately not represented as issuance/truth.
    validate(envelope)
    with pytest.raises(SemanticContractError, match="translation_replay_mismatch"):
        verify_read_translation(
            canonical_bytes(envelope),
            SOURCE,
            context(),
            adapter_id=QBO_ADAPTER,
            adapter_version="1.0.0",
        )


@pytest.mark.parametrize(
    "location,field,replacement",
    [
        ("root", "organization_id", str(uuid4())),
        ("source", "account_id", "98765"),
        ("source", "artifact_receipt_id", str(uuid4())),
        ("source", "raw_bytes_sha256", "0" * 64),
        ("source", "captured_at", "2026-10-03T17:31:00.000000Z"),
        ("source", "environment", "owner_preview"),
        ("source", "provider", "microsoft_365"),
        ("adapter", "version", "1.0.1"),
        ("adapter", "configuration_digest", "0" * 64),
        ("adapter", "mapping_digest", "0" * 64),
        ("adapter", "artifact_digest", "0" * 64),
        ("root", "schema_digest", "0" * 64),
        ("root", "semantic_profile_digest", "0" * 64),
        ("subject", "namespace", "other.namespace"),
        ("subject", "entity_id", "2"),
    ],
)
def test_scope_version_and_provenance_substitution_rejected_even_with_valid_digest(
    location, field, replacement
):
    envelope = qbo().envelope()
    target = (
        envelope["payload"] if location == "root" else envelope["payload"][location]
    )
    target[field] = replacement
    with pytest.raises(SemanticContractError):
        validate(rehash(envelope))


@pytest.mark.parametrize(
    "mutation",
    [
        "observed",
        "new_concept",
        "wrong_pointer",
        "complete",
        "duplicate_concept",
        "invented_time",
        "new_field",
        "write",
    ],
)
def test_authority_and_semantic_claim_escalation_fail_closed(mutation):
    envelope = qbo().envelope()
    payload = envelope["payload"]
    if mutation == "observed":
        payload["assertions"][0]["evidence_kind"] = "observed"
    elif mutation == "new_concept":
        payload["assertions"][0]["concept_id"] = "entity.legal_name"
    elif mutation == "wrong_pointer":
        payload["assertions"][0]["source_pointer"] = "/CompanyInfo/LegalName"
    elif mutation == "complete":
        payload["coverage"]["state"] = "complete"
        payload["coverage"]["gaps"] = []
    elif mutation == "duplicate_concept":
        payload["assertions"].append(copy.deepcopy(payload["assertions"][0]))
    elif mutation == "invented_time":
        payload["assertions"][0]["effective_time"]["utc"] = payload["source"][
            "captured_at"
        ]
    elif mutation == "new_field":
        payload["admitted"] = True
    elif mutation == "write":
        payload["operation"] = "invoice.create"
    with pytest.raises(SemanticContractError):
        validate(rehash(envelope))


@pytest.mark.parametrize(
    "raw",
    [
        b'{"x":1,"x":2}',
        b'{"x":1,"\\u0078":2}',
        b'{"x":NaN}',
        b'{"x":Infinity}',
        b'{"x":"\\ud800"}',
        b"\xff",
        b"[" * 40 + b"0" + b"]" * 40,
        b" " * (MAX_BYTES + 1),
    ],
    ids=[
        "duplicate",
        "escaped-duplicate",
        "nan",
        "infinity",
        "surrogate",
        "utf8",
        "depth",
        "oversized",
    ],
)
def test_hostile_json_is_bounded_and_rejected(raw):
    with pytest.raises(SemanticContractError):
        parse_json(raw, source=True)


def test_provider_decimal_parsing_preserves_exact_values_before_mapping():
    parsed = parse_json(b'{"amount":9007199254740993.0001}', source=True)
    assert parsed["amount"] == Decimal("9007199254740993.0001")
    assert exact_decimal(parsed["amount"]) == "9007199254740993.0001"
    with pytest.raises(SemanticContractError):
        canonical_bytes(parsed)  # must become an explicit exact decimal string


@pytest.mark.parametrize(
    "value", [0.1, float("nan"), 9007199254740992, Decimal("1.00")]
)
def test_canonical_wire_domain_rejects_float_decimal_objects_and_unsafe_integer(value):
    with pytest.raises(SemanticContractError):
        canonical_bytes({"value": value})


@pytest.mark.parametrize(
    "value",
    [
        {"type": "integer", "data": 0, "unit": "count"},
        {"type": "boolean", "data": False},
        {"type": "text", "data": ""},
        {
            "type": "money",
            "data": "0",
            "currency": "USD",
            "currency_registry": "stewardence.currency-subset.v1",
            "source_scale": 2,
        },
    ],
)
def test_known_zero_false_and_empty_survive_without_truthiness_coercion(value):
    validate_assertion(assertion(value=value))


@pytest.mark.parametrize(
    "state", ["missing", "unknown", "unavailable", "unsupported", "redacted"]
)
def test_nonvalue_states_forbid_values(state):
    item = assertion(state)
    validate_assertion(item)
    item["value"] = None
    with pytest.raises(SemanticContractError):
        validate_assertion(item)


@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_boolean_float_and_string_cannot_impersonate_integer(value):
    with pytest.raises(SemanticContractError):
        validate_assertion(
            assertion(value={"type": "integer", "data": value, "unit": "count"})
        )


@pytest.mark.parametrize(
    "data,scale,currency",
    [
        ("1.01", 1, "USD"),
        ("-0", 2, "USD"),
        ("1.00", 2, "USD"),
        ("1e3", 2, "USD"),
        ("1", 2, "XYZ"),
        ("0.1", True, "USD"),
    ],
)
def test_money_precision_lexical_forms_and_currency_registry_are_closed(
    data, scale, currency
):
    with pytest.raises(SemanticContractError):
        validate_assertion(
            assertion(
                value={
                    "type": "money",
                    "data": data,
                    "currency": currency,
                    "currency_registry": "stewardence.currency-subset.v1",
                    "source_scale": scale,
                }
            )
        )


def test_explicit_offset_time_is_checked_without_inventing_time_for_dates():
    item = assertion()
    item["effective_time"] = {
        "source_text": "2026-10-03T12:30:00-05:00",
        "utc": "2026-10-03T17:30:00.000000Z",
    }
    validate_assertion(item)
    item["effective_time"] = {"source_text": "2026-10-03", "utc": None}
    validate_assertion(item)
    item["effective_time"]["utc"] = "2026-10-03T00:00:00.000000Z"
    with pytest.raises(SemanticContractError):
        validate_assertion(item)


@pytest.mark.parametrize(
    "source,utc",
    [
        ("2026-02-30T12:30:00Z", "2026-02-30T12:30:00.000000Z"),
        ("2026-10-03T12:30:00-00:00", "2026-10-03T12:30:00.000000Z"),
        ("2026-10-03T12:30:00.1234567Z", "2026-10-03T12:30:00.123456Z"),
        ("2026-10-03T12:30:00-05:00", "2026-10-03T12:30:00.000000Z"),
    ],
)
def test_unknown_offsets_precision_loss_and_invalid_dates_rejected(source, utc):
    item = assertion()
    item["effective_time"] = {"source_text": source, "utc": utc}
    with pytest.raises(SemanticContractError):
        validate_assertion(item)


def test_jcs_utf16_order_array_order_and_unicode_not_normalized():
    value = {"\ue000": "private", "\U0001f600": "emoji", "a": ["e\u0301", "\u00e9"]}
    assert (
        canonical_bytes(value) == '{"a":["é","é"],"😀":"emoji","":"private"}'.encode()
    )
    assert digest(["a", "b"]) != digest(["b", "a"])
    assert digest("e\u0301") != digest("\u00e9")


@pytest.mark.parametrize("version", ["latest", "1.0", "2.0.0", "1.0.1"])
def test_unregistered_adapter_update_cannot_reinterpret_old_record(version):
    with pytest.raises(SemanticContractError, match="unregistered_adapter"):
        normalize_read(
            SOURCE, context(), adapter_id=QBO_ADAPTER, adapter_version=version
        )


def test_errors_do_not_echo_provider_payloads():
    secret_marker = "sensitive-fixture-value"
    with pytest.raises(SemanticContractError) as error:
        qbo(
            json.dumps(
                {
                    "CompanyInfo": {
                        "Id": "1",
                        "CompanyName": {"access_token": secret_marker},
                    }
                }
            ).encode()
        )
    assert secret_marker not in str(error.value)


@pytest.mark.parametrize("kind", ["observed", "inferred", "calculated"])
def test_unqualified_observation_or_derivation_basis_is_not_admitted(kind):
    item = assertion()
    item["evidence_kind"] = kind
    with pytest.raises(SemanticContractError):
        validate_assertion(item)


@pytest.mark.parametrize("source", ["2026-02-30", "not-a-time", "2026-10-03T25:00:00Z"])
def test_unresolved_time_does_not_accept_invalid_calendar_text(source):
    item = assertion()
    item["effective_time"] = {"source_text": source, "utc": None}
    with pytest.raises(SemanticContractError, match="invalid_effective_time"):
        validate_assertion(item)


def test_unrepresentable_source_exponent_has_fixed_rejection_code():
    with pytest.raises(SemanticContractError, match="unsupported_numeric_exponent"):
        parse_json(b'{"unused":1e999999999999999999999999}', source=True)


def test_schema_bytes_changed_under_old_identity_fail_closed(tmp_path, monkeypatch):
    import shutil

    import apps.integrations.semantics.contracts as contracts

    shutil.copytree(
        contracts.ROOT,
        tmp_path / "bundle",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    monkeypatch.setattr(contracts, "ROOT", tmp_path / "bundle")
    path = contracts.ROOT / "schemas/read-payload-v1.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(SemanticContractError, match="bundled_contract_drift"):
        bundled_contract()


def test_schema_error_has_no_secret_retaining_validation_exception_context():
    import traceback

    marker = "private-marker-not-for-logs"
    raw = json.dumps(
        {"CompanyInfo": {"Id": "1", "CompanyName": marker + "x" * 201}}
    ).encode()
    with pytest.raises(SemanticContractError) as caught:
        qbo(raw)
    error = caught.value
    assert str(error) == "schema_validation_failed"
    assert error.__context__ is None
    assert error.__cause__ is None
    assert marker not in "".join(traceback.format_exception(error))


def test_json_decode_error_does_not_retain_source_in_exception_chain():
    import traceback

    marker = "private-marker-not-for-logs"
    raw = ('{"CompanyInfo":"' + marker + '",bad}').encode()
    with pytest.raises(SemanticContractError) as caught:
        qbo(raw)
    assert caught.value.__context__ is None
    assert marker not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "token", ["1e59", "9" * 60, "-1e59", "0.00", "1e-18", "-1e-18", "123.45000"]
)
def test_exact_decimal_normalize_validate_and_idempotence_at_boundaries(token):
    number = Decimal(token)
    normalized = exact_decimal(number)
    item = assertion(
        value={"type": "decimal", "data": normalized, "unit": "1", "source_scale": 18}
    )
    validate_assertion(item)
    assert Decimal(normalized) == number
    assert exact_decimal(Decimal(normalized)) == normalized


@pytest.mark.parametrize("token", ["1e60", "-1e60", "1e-19", "9" * 61])
def test_decimal_expansion_outside_closed_wire_domain_is_rejected(token):
    with pytest.raises(SemanticContractError, match="decimal_precision_bound"):
        exact_decimal(Decimal(token))


@pytest.mark.parametrize("offset", ["+00:60", "-00:99", "+24:00"])
@pytest.mark.parametrize("with_utc", [True, False])
def test_malformed_offset_components_cannot_be_normalized_by_python(offset, with_utc):
    item = assertion()
    item["effective_time"] = {
        "source_text": "2026-10-03T12:30:00" + offset,
        "utc": "2026-10-03T11:30:00.000000Z" if with_utc else None,
    }
    with pytest.raises(SemanticContractError):
        validate_assertion(item)


@pytest.mark.parametrize(
    "stamp",
    [
        datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        datetime(9999, 12, 31, 23, 59, tzinfo=timezone(timedelta(hours=-1))),
    ],
)
def test_capture_utc_conversion_range_failures_have_fixed_code(stamp):
    from dataclasses import replace

    with pytest.raises(SemanticContractError, match="utc_range_invalid") as caught:
        replace(context(), captured_at=stamp)
    assert caught.value.__context__ is None


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_file",
        "extra_file",
        "artifact_digest",
        "mapping",
        "configuration_digest",
        "enabled",
        "extra_metadata",
    ],
)
def test_registry_inventory_and_digest_derivations_are_verified(
    tmp_path, monkeypatch, mutation
):
    import shutil

    import apps.integrations.semantics.contracts as contracts

    shutil.copytree(
        contracts.ROOT,
        tmp_path / "bundle",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    monkeypatch.setattr(contracts, "ROOT", tmp_path / "bundle")
    path = contracts.ROOT / "registry-v1.json"
    manifest = json.loads(path.read_bytes())
    if mutation == "missing_file":
        del manifest["files"]["schemas/read-envelope-v1.json"]
    elif mutation == "extra_file":
        manifest["files"]["unexpected.py"] = "0" * 64
    elif mutation == "artifact_digest":
        manifest["artifact_digest"] = "0" * 64
    elif mutation == "mapping":
        manifest["adapters"][0]["pointers"]["entity.display_name"] = (
            "/CompanyInfo/LegalName"
        )
    elif mutation == "configuration_digest":
        manifest["adapters"][0]["configuration_digest"] = "0" * 64
    elif mutation == "enabled":
        manifest["writes_enabled"] = True
    elif mutation == "extra_metadata":
        manifest["authority"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SemanticContractError):
        bundled_contract()


def test_direct_content_constructor_validates_bytes_and_canonical_form():
    with pytest.raises(SemanticContractError):
        ValidatedReadEvidence(b"{}")
    with pytest.raises(SemanticContractError):
        ValidatedReadEvidence(bytearray(qbo().canonical_payload))
    with pytest.raises(SemanticContractError, match="noncanonical_content"):
        ValidatedReadEvidence(json.dumps(qbo().payload(), indent=2).encode())


def test_verify_replay_applies_source_bound_before_hashing():
    with pytest.raises(SemanticContractError, match="json_byte_bound"):
        verify_read_translation(
            b"{}",
            b"x" * (MAX_BYTES + 1),
            context(),
            adapter_id=QBO_ADAPTER,
            adapter_version="1.0.0",
        )


def test_canonical_output_checks_preallocation_budget_before_serializer(monkeypatch):
    import apps.integrations.semantics.contracts as contracts

    def must_not_run(_):
        raise AssertionError("Serializer called before size rejection")

    monkeypatch.setattr(contracts.rfc8785, "dumps", must_not_run)
    with pytest.raises(SemanticContractError, match="json_byte_bound"):
        canonical_bytes({"value": "x" * MAX_BYTES})


def test_language_agnostic_request_and_response_pin_the_same_interpretation():
    request = prepare_read_request(
        SOURCE, context(), adapter_id=QBO_ADAPTER, adapter_version="1.0.0"
    )
    result = normalize_request(request, SOURCE)
    assert result == qbo()
    assert (
        normalize_request(request, SOURCE).canonical_payload == result.canonical_payload
    )


@pytest.mark.parametrize(
    "field",
    [
        "request_schema_digest",
        "target_schema_digest",
        "semantic_profile_digest",
        "artifact_digest",
        "mapping_digest",
        "configuration_digest",
    ],
)
def test_queued_request_cannot_silently_change_interpretation(field):
    request = json.loads(
        prepare_read_request(
            SOURCE, context(), adapter_id=QBO_ADAPTER, adapter_version="1.0.0"
        )
    )
    target = (
        request["adapter"]
        if field in {"artifact_digest", "mapping_digest", "configuration_digest"}
        else request
    )
    target[field] = "0" * 64
    with pytest.raises(SemanticContractError, match="normalization_pin_mismatch"):
        normalize_request(canonical_bytes(request), SOURCE)


def test_request_source_substitution_and_write_fields_are_rejected():
    request = prepare_read_request(
        SOURCE, context(), adapter_id=QBO_ADAPTER, adapter_version="1.0.0"
    )
    with pytest.raises(SemanticContractError, match="source_binding_mismatch"):
        normalize_request(request, b'{"CompanyInfo":{"Id":"2"}}')
    forged = json.loads(request)
    forged["write_authorized"] = True
    with pytest.raises(SemanticContractError, match="schema_validation_failed"):
        normalize_request(canonical_bytes(forged), SOURCE)


def test_graph_id_rejection_does_not_retain_private_marker_in_exception_chain():
    import traceback

    marker = "private-marker-in-id-1234567890zz"
    ctx = context("microsoft_365")
    raw = json.dumps({"value": [{"id": marker}]}).encode()
    with pytest.raises(SemanticContractError) as caught:
        normalize_read(raw, ctx, adapter_id=MS_ADAPTER, adapter_version="1.0.0")
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert marker not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "pointer", ["", "/", "/a~0b", "/a~1b/0", "/name/🚀", "//" * 200]
)
def test_json_pointer_valid_vectors(pointer):
    item = assertion()
    item["source_pointer"] = pointer
    validate_assertion(item)


@pytest.mark.parametrize("pointer", ["\n", "~2\n", "/invalid~2\n"])
def test_json_pointer_rejects_final_newline_anchor_bypass(pointer):
    item = assertion()
    item["source_pointer"] = pointer
    with pytest.raises(SemanticContractError):
        validate_assertion(item)


def test_hostile_pointer_rejection_is_bounded_by_a_process_timeout():
    import subprocess
    import sys

    program = """
from apps.integrations.semantics.contracts import SemanticContractError,validate_assertion
item={'concept_id':'fixture.measurement','concept_version':1,'evidence_kind':'declared',
 'value_state':'known','value':{'type':'text','data':'x'},
 'source_pointer':'/'*500+'~2','effective_time':{'source_text':None,'utc':None}}
rejected=False
try:
 validate_assertion(item)
except SemanticContractError:
 rejected=True
if not rejected:
 raise SystemExit('Invalid JSON Pointer accepted')
"""
    # A regression to ambiguous nested repetition would be terminated here,
    # rather than hanging the parent qualification process indefinitely.
    result = subprocess.run(
        [sys.executable, "-c", program], capture_output=True, timeout=10
    )
    assert result.returncode == 0, result.stderr.decode()
