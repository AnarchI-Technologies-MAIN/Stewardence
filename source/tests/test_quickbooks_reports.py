import hashlib
import json
from datetime import date, datetime, timedelta

import httpx
import pytest
from django.core.exceptions import PermissionDenied
from django.utils import timezone

from apps.integrations import quickbooks_services as service
from apps.integrations.forms import SandboxReportForm
from apps.integrations.models import QuickBooksEvent
from apps.integrations.quickbooks_client import OAuthError
from apps.integrations.quickbooks_reports import ReportPeriod, report_evidence
from apps.organizations.models import Organization, OrganizationMember
from tests.test_quickbooks_client import make_client
from tests.test_quickbooks_lifecycle import connected
from tests.test_quickbooks_lifecycle import setup as lifecycle_setup

setup = lifecycle_setup

PERIOD = ReportPeriod(date(2026, 1, 1), date(2026, 1, 31), "Accrual")


def source_report():
    return {
        "Header": {
            "ReportName": "ProfitAndLoss",
            "StartPeriod": "2026-01-01",
            "EndPeriod": "2026-01-31",
            "ReportBasis": "Accrual",
            "Currency": "USD",
            "SummarizeColumnsBy": "Total",
        },
        "Columns": {"Column": [{"ColType": "Account"}, {"ColType": "Money"}]},
        "Rows": {
            "Row": [{"ColData": [{"value": "Example expense"}, {"value": "123.45"}]}]
        },
    }


def source_bytes():
    return json.dumps(source_report(), indent=2).encode()


def test_report_transport_is_one_bounded_sandbox_get():
    calls = []

    def handler(request):
        calls.append(request)
        assert request.method == "GET"
        assert request.url.host == "sandbox-quickbooks.api.intuit.com"
        assert request.url.path == "/v3/company/12345/reports/ProfitAndLoss"
        assert dict(request.url.params) == PERIOD.parameters()
        assert request.headers["authorization"] == "Bearer private-access"
        assert not request.content
        return httpx.Response(200, content=source_bytes())

    assert (
        make_client(handler).profit_and_loss("12345", "private-access", PERIOD)
        == source_bytes()
    )
    assert len(calls) == 1


@pytest.mark.parametrize(
    "realm,token,period",
    [
        ("../escape", "token", PERIOD),
        ("123?x=y", "token", PERIOD),
        ("123", "bad\nheader", PERIOD),
        ("123", "token", {}),
    ],
)
def test_report_bad_transport_arguments_never_call_provider(realm, token, period):
    calls = []
    with pytest.raises(OAuthError):
        make_client(lambda r: calls.append(r)).profit_and_loss(realm, token, period)
    assert not calls


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_report_error_never_follows_redirect_or_returns_provider_body(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://attacker.invalid"},
            json={"Fault": {"Detail": "PRIVATE FINANCIAL DATA"}},
        )

    with pytest.raises(OAuthError) as error:
        make_client(handler).profit_and_loss("12345", "token", PERIOD)
    assert "PRIVATE" not in str(error.value)
    assert len(calls) == 1


def test_report_size_bound():
    with pytest.raises(OAuthError, match="provider_response_too_large"):
        make_client(
            lambda r: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
        ).profit_and_loss("123", "token", PERIOD)


def test_export_preserves_exact_bytes_and_period_semantics():
    source = source_report()
    source["Rows"]["Row"][0]["ColData"][0]["value"] = "Café – source label"
    raw = json.dumps(source, ensure_ascii=False, indent=3).encode()
    evidence = report_evidence(raw, PERIOD)
    assert evidence["source_json"].encode() == raw
    assert evidence["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert evidence["period_end_exclusive"] == "2026-02-01"
    assert evidence["provider_period_end_inclusive"] == "2026-01-31"
    assert evidence["roi_status"] == "not_calculated"
    assert evidence["currency"] == "USD"
    assert evidence["completeness"] == "not_independently_established"


@pytest.mark.parametrize(
    "field,value",
    [
        ("ReportName", "BalanceSheet"),
        ("StartPeriod", "2025-01-01"),
        ("EndPeriod", "2026-02-01"),
        ("ReportBasis", "Cash"),
        ("Currency", ""),
        ("Currency", ["USD"]),
        ("SummarizeColumnsBy", "Month"),
    ],
)
def test_report_metadata_mismatch_is_rejected(field, value):
    source = source_report()
    source["Header"][field] = value
    with pytest.raises(OAuthError, match="invalid_report_response"):
        report_evidence(json.dumps(source).encode(), PERIOD)


@pytest.mark.parametrize(
    "raw",
    [
        b"{}",
        b"[]",
        b"null",
        b"<html>PRIVATE</html>",
        b'{"Header": {}, "Header": {}}',
        b'{"value": NaN}',
        b"\xff",
        b"[" * 1100 + b"]" * 1100,
    ],
)
def test_invalid_json_is_rejected_without_payload_in_error(raw):
    with pytest.raises(OAuthError, match="invalid_report_response") as error:
        report_evidence(raw, PERIOD)
    assert "PRIVATE" not in str(error.value)


def test_empty_report_does_not_fabricate_zero_metrics():
    source = source_report()
    source["Rows"] = {}
    result = report_evidence(json.dumps(source).encode(), PERIOD)
    assert result["interpretation"] == "source_report_only"
    assert "net_income" not in result
    assert json.loads(result["source_json"])["Rows"] == {}


def test_numeric_precision_is_preserved_in_source():
    raw = source_bytes().replace(b'"123.45"', b"123456789.1234567890123456789")
    assert report_evidence(raw, PERIOD)["source_json"].encode() == raw


@pytest.mark.parametrize(
    "start,end,basis",
    [
        (date(2026, 2, 1), date(2026, 1, 1), "Cash"),
        (date(2026, 1, 1), date(2026, 4, 3), "Cash"),
        (datetime(2026, 1, 1), date(2026, 1, 31), "Cash"),
        (date(2026, 1, 1), date(2026, 1, 31), "Default"),
    ],
)
def test_period_bounds(start, end, basis):
    with pytest.raises(OAuthError, match="invalid_report_period"):
        ReportPeriod(start, end, basis)


def test_single_day_and_92_day_periods_are_supported():
    ReportPeriod(date(2026, 1, 1), date(2026, 1, 1), "Cash")
    ReportPeriod(date(2026, 1, 1), date(2026, 4, 2), "Accrual")


def form_data():
    return {
        "start_date": "2026-01-01",
        "end_date": "2026-01-31",
        "accounting_basis": "Accrual",
        "authorize_export": "on",
    }


def test_form_requires_explicit_basis_and_export_authorization():
    for field in ["accounting_basis", "authorize_export"]:
        data = form_data()
        data.pop(field)
        assert not SandboxReportForm(data).is_valid()


@pytest.mark.django_db(transaction=True)
def test_export_service_returns_scoped_evidence_and_records_only_lifecycle(setup):
    obj = connected(setup)
    before = obj.encrypted_credentials
    setup[2].profit_and_loss.return_value = source_bytes()
    result = service.export_profit_and_loss(setup[0], setup[1].id, PERIOD)
    assert result["connection_reference"] == str(obj.id)
    assert result["workspace_id"] == str(setup[1].id)
    event = QuickBooksEvent.objects.get(id=result["audit_event_id"])
    assert event.kind == "report_export_prepared"
    obj.refresh_from_db()
    assert obj.encrypted_credentials == before
    assert "fake-access" not in json.dumps(result)
    assert "fake-refresh" not in json.dumps(result)
    with pytest.raises(OAuthError, match="report_export_rate_limited"):
        service.export_profit_and_loss(setup[0], setup[1].id, PERIOD)
    assert setup[2].profit_and_loss.call_count == 1


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("failure", ["provider", "metadata"])
def test_report_failure_is_recorded_without_success(setup, failure):
    connected(setup)
    setup[2].profit_and_loss.return_value = b"{}"
    if failure == "provider":
        setup[2].profit_and_loss.side_effect = OAuthError(
            "provider_temporarily_unavailable"
        )
    with pytest.raises(OAuthError):
        service.export_profit_and_loss(setup[0], setup[1].id, PERIOD)
    assert QuickBooksEvent.objects.filter(kind="report_export_failed").count() == 1
    assert not QuickBooksEvent.objects.filter(kind="report_export_prepared").exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "blocked",
    [
        "expired",
        "refresh_expired",
        "disconnected",
        "revoking",
        "foreign",
        "role",
        "allowlist",
        "disabled",
    ],
)
def test_report_service_authority_before_network(setup, settings, blocked):
    obj = connected(setup)
    org_id = setup[1].id
    if blocked == "expired":
        obj.access_expires_at = timezone.now() - timedelta(seconds=1)
    if blocked == "refresh_expired":
        obj.refresh_expires_at = timezone.now()
    if blocked in ["disconnected", "revoking"]:
        obj.status = blocked
    obj.save()
    if blocked == "foreign":
        org_id = Organization.objects.create(name="Foreign").id
    if blocked == "role":
        OrganizationMember.objects.filter(user=setup[0]).update(role="admin")
    if blocked == "allowlist":
        settings.QUICKBOOKS_SANDBOX_USER_IDS = []
    if blocked == "disabled":
        settings.QUICKBOOKS_SANDBOX_ENABLED = False
    with pytest.raises((OAuthError, PermissionDenied)):
        service.export_profit_and_loss(setup[0], org_id, PERIOD)
    setup[2].profit_and_loss.assert_not_called()


def login(client, setup):
    client.force_login(setup[0])
    session = client.session
    session["active_organization_id"] = str(setup[1].id)
    session.save()


@pytest.mark.django_db(transaction=True)
def test_download_is_post_only_attachment_with_private_headers(setup, client):
    connected(setup)
    setup[2].profit_and_loss.return_value = source_bytes()
    login(client, setup)
    path = "/integrations/quickbooks/export-report/"
    assert client.get(path, secure=True).status_code == 405
    response = client.post(path, form_data(), secure=True)
    assert response.status_code == 200
    assert response["Content-Disposition"].startswith("attachment;")
    assert response["Cache-Control"] == "no-cache, no-store"
    assert response["X-Content-Type-Options"] == "nosniff"
    result = json.loads(response.content)
    assert result["source_sha256"] == hashlib.sha256(source_bytes()).hexdigest()
    assert result["roi_status"] == "not_calculated"


@pytest.mark.django_db(transaction=True)
def test_export_requires_csrf(setup):
    from django.test import Client

    connected(setup)
    client = Client(enforce_csrf_checks=True)
    login(client, setup)
    assert (
        client.post(
            "/integrations/quickbooks/export-report/", form_data(), secure=True
        ).status_code
        == 403
    )
    setup[2].profit_and_loss.assert_not_called()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "bad", ["missing_authorization", "missing_basis", "duplicate", "foreign_parameter"]
)
def test_invalid_export_form_never_calls_provider(setup, client, bad):
    connected(setup)
    login(client, setup)
    data = form_data()
    if bad == "missing_authorization":
        data.pop("authorize_export")
    if bad == "missing_basis":
        data.pop("accounting_basis")
    if bad == "duplicate":
        data["start_date"] = ["2026-01-01", "2026-01-02"]
    if bad == "foreign_parameter":
        data["realm_id"] = "999"
    assert client.post(
        "/integrations/quickbooks/export-report/", data, secure=True
    ).status_code in [400, 403]
    setup[2].profit_and_loss.assert_not_called()
