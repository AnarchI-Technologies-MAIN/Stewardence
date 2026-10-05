import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from apps.integrations.quickbooks_client import (
    DISCOVERY_URL,
    ENDPOINTS,
    OAuthConfig,
    OAuthError,
    QuickBooksClient,
    validate_token,
)
from apps.integrations.quickbooks_crypto import CredentialError


def tokens():
    return {
        "access_token": "private-access",
        "refresh_token": "private-refresh",
        "token_type": "bearer",
        "expires_in": 3600,
        "x_refresh_token_expires_in": 8640000,
    }


def make_client(handler):
    return QuickBooksClient(
        OAuthConfig(
            "client",
            "secret",
            "https://www.stewardence.com/integrations/quickbooks/callback/",
        ),
        transport=httpx.MockTransport(handler),
    )


def test_discovery_and_auth_url_scope_state_redirect():
    def handler(request):
        assert str(request.url) == DISCOVERY_URL
        assert "authorization" not in request.headers
        return httpx.Response(200, json=ENDPOINTS)

    client = make_client(handler)
    params = parse_qs(urlsplit(client.authorization_url("nonce")).query)
    assert params["scope"] == ["com.intuit.quickbooks.accounting"]
    assert params["state"] == ["nonce"]
    assert params["redirect_uri"] == [client.config.redirect_uri]


def test_discovery_cannot_exfiltrate_secret():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200, json={**ENDPOINTS, "token_endpoint": "https://attacker.invalid/tokens"}
        )

    with pytest.raises(OAuthError, match="discovery_endpoint_change"):
        make_client(handler).tokens(code="code")
    assert len(calls) == 1
    assert "authorization" not in calls[0].headers


@pytest.mark.parametrize("mode", ["code", "refresh"])
def test_server_side_exchange_and_rotation(mode):
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=ENDPOINTS)
        assert str(request.url) == ENDPOINTS["token_endpoint"]
        assert request.headers["authorization"].startswith("Basic ")
        assert b"private" not in str(request.url).encode()
        return httpx.Response(200, json=tokens())

    kwargs = {"code": "code"} if mode == "code" else {"refresh_token": "old-refresh"}
    result = make_client(handler).tokens(**kwargs)
    assert result["refresh_token"] == "private-refresh"
    assert len(calls) == 2


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (400, {"error": "invalid_grant", "secret": "DO-NOT-LOG"}, "reconnect_required"),
        (
            429,
            {"error": "rate_limit", "secret": "DO-NOT-LOG"},
            "provider_temporarily_unavailable",
        ),
        (503, {}, "provider_temporarily_unavailable"),
        (401, {"error": "invalid_client"}, "provider_rejected_request"),
    ],
)
def test_errors_are_bounded_and_sanitized(status, body, expected):
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=ENDPOINTS)
        return httpx.Response(status, json=body)

    with pytest.raises(OAuthError, match=expected) as error:
        make_client(handler).tokens(code="private-code")
    assert "DO-NOT-LOG" not in str(error.value)
    assert len(calls) == 2  # No blind retries of consumed codes or invalid grants.


def test_redirect_not_followed():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            302, headers={"Location": "https://attacker.invalid"}, json={}
        )

    with pytest.raises(OAuthError):
        make_client(handler).authorization_url("nonce")
    assert len(calls) == 1


def test_oversized_response_rejected():
    with pytest.raises(OAuthError, match="too_large"):
        make_client(
            lambda request: httpx.Response(200, content=b"x" * 65537)
        ).discover()


@pytest.mark.parametrize(
    "field,value",
    [
        ("expires_in", True),
        ("expires_in", -1),
        ("expires_in", "3600"),
        ("token_type", "other"),
        ("access_token", ""),
        ("refresh_token", "header\ninjection"),
    ],
)
def test_malformed_tokens_rejected(field, value):
    with pytest.raises(OAuthError):
        validate_token({**tokens(), field: value})


def test_empty_successful_revocation():
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=ENDPOINTS)
        assert str(request.url) == ENDPOINTS["revocation_endpoint"]
        assert json.loads(request.content) == {"token": "private-refresh"}
        return httpx.Response(200)

    make_client(handler).revoke("private-refresh")


def test_company_check_is_fixed_sandbox_get_and_discards_company_data():
    def handler(request):
        assert request.method == "GET"
        assert str(request.url) == (
            "https://sandbox-quickbooks.api.intuit.com/v3/company/12345/companyinfo/12345"
        )
        assert request.headers["authorization"] == "Bearer private-access"
        assert not request.content
        return httpx.Response(
            200,
            json={
                "CompanyInfo": {
                    "Id": "1",
                    "CompanyName": "PRIVATE COMPANY",
                    "Email": "PRIVATE EMAIL",
                }
            },
        )

    assert make_client(handler).verify_company_access("12345", "private-access") is None


@pytest.mark.parametrize(
    "realm,token",
    [
        ("../company", "token"),
        ("https://attacker.invalid", "token"),
        ("12345?redirect=evil", "token"),
        (12345, "token"),
        ("12345", "bad\nheader"),
        ("12345", ""),
    ],
)
def test_company_check_rejects_invalid_inputs_without_network(realm, token):
    calls = []
    with pytest.raises(OAuthError, match="invalid_company_check"):
        make_client(lambda request: calls.append(request)).verify_company_access(
            realm, token
        )
    assert calls == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        [],
        {"CompanyInfo": {}},
        {"CompanyInfo": {"Id": "1"}},
        {"CompanyInfo": {"Id": 1, "CompanyName": "Private"}},
        {"CompanyInfo": {"Id": "1", "CompanyName": " "}},
        {"Fault": {}, "CompanyInfo": {"Id": "1", "CompanyName": "Private"}},
    ],
)
def test_company_check_does_not_accept_unverified_response(body):
    with pytest.raises(OAuthError, match="invalid_company_response"):
        make_client(
            lambda request: httpx.Response(200, json=body)
        ).verify_company_access("12345", "token")


@pytest.mark.parametrize("status", [302, 401, 403, 429, 500])
def test_company_check_provider_failure_is_sanitized_and_not_retried(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            status,
            headers={"Location": "https://attacker.invalid"},
            json={"Fault": {"message": "PRIVATE COMPANY"}},
        )

    with pytest.raises(OAuthError) as error:
        make_client(handler).verify_company_access("12345", "private-access")
    assert "PRIVATE" not in str(error.value)
    assert len(calls) == 1


def test_company_check_bounds_response_size():
    with pytest.raises(OAuthError, match="provider_response_too_large"):
        make_client(
            lambda request: httpx.Response(200, content=b"x" * 65537)
        ).verify_company_access("12345", "token")


def test_company_transport_does_not_log_realm_or_company_data(settings):
    # pytest's logging capture can alter logger propagation. Exercise Django's
    # startup logging in a fresh process, as it runs in the application.
    import os
    import subprocess
    import sys

    code = """
import django
import logging
import httpx
django.setup()
from apps.integrations.quickbooks_client import OAuthConfig, QuickBooksClient
logging.basicConfig(level=logging.DEBUG)
logging.getLogger('httpx').setLevel(logging.DEBUG)
logging.getLogger('httpcore').setLevel(logging.DEBUG)
client = QuickBooksClient(OAuthConfig('fake', 'fake', 'https://example.invalid'),
    transport=httpx.MockTransport(lambda request: httpx.Response(200,
        json={'CompanyInfo': {'Id': '1', 'CompanyName': 'PRIVATE COMPANY'}})))
client.verify_company_access('987654321', 'private-access')
print('CHECK_COMPLETE')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=settings.BASE_DIR,
        env={
            **os.environ,
            "PYTHONPATH": "src:.",
            "DJANGO_SETTINGS_MODULE": "agentledger.settings.development",
        },
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0
    assert "CHECK_COMPLETE" in result.stdout
    output = result.stdout + result.stderr
    assert "987654321" not in output
    assert "PRIVATE COMPANY" not in output
    assert "private-access" not in output


def test_configuration_disabled_and_production_forbidden(settings, tmp_path):
    settings.QUICKBOOKS_SANDBOX_ENABLED = False
    with pytest.raises(OAuthError, match="disabled"):
        OAuthConfig.load()
    settings.QUICKBOOKS_SANDBOX_ENABLED = True
    settings.DEBUG = False
    path = tmp_path / "client.json"
    path.write_text(
        json.dumps(
            {
                "environment": "production",
                "client_id": "client",
                "client_secret": "secret",
            }
        )
    )
    path.chmod(0o600)
    settings.QUICKBOOKS_CLIENT_FILE = str(path)
    settings.QUICKBOOKS_REDIRECT_URI = (
        "https://www.stewardence.com/integrations/quickbooks/callback/"
    )
    settings.ALLOWED_HOSTS = ["www.stewardence.com"]
    with pytest.raises(CredentialError):
        OAuthConfig.load()
