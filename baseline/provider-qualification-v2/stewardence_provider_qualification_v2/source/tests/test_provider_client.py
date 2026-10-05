from dataclasses import replace
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import httpx
import pytest

from apps.integrations.provider_client import (
    MS_CLIENT,
    MS_TENANT,
    SCOPES,
    ProviderClient,
    ProviderConfig,
    strict_json,
)
from apps.integrations.quickbooks_client import OAuthError


@pytest.fixture(params=["microsoft", "xero"])
def config(request):
    provider = request.param
    return ProviderConfig(
        provider,
        MS_CLIENT if provider == "microsoft" else "X" * 32,
        "secret-test-only",
        str(uuid4()),
        f"https://www.stewardence.com/integrations/{provider}/callback/",
        MS_TENANT if provider == "microsoft" else "",
    )


def test_authorization_uses_fixed_host_and_microsoft_pkce(config):
    url = ProviderClient(config).authorization_url("a" * 43, "v" * 64)
    parsed = urlsplit(url)
    assert parsed.hostname == (
        "login.microsoftonline.com"
        if config.provider == "microsoft"
        else "login.xero.com"
    )
    query = parse_qs(parsed.query)
    assert query["redirect_uri"] == [config.redirect_uri]
    assert query["scope"] == [" ".join(SCOPES[config.provider])]
    assert config.client_secret not in url
    assert ("code_challenge" in query) == (config.provider == "microsoft")
    if config.provider == "microsoft":
        assert MS_TENANT in parsed.path and "/common/" not in parsed.path
        assert query["code_challenge_method"] == ["S256"]


def token_response(config):
    return {
        "access_token": "access-test-only",
        "refresh_token": "refresh-test-only",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": " ".join(SCOPES[config.provider]),
    }


def test_tokens_use_fixed_endpoint_and_discard_id_token(config):
    requests = []

    def handle(req):
        requests.append(req)
        return httpx.Response(
            200, json={**token_response(config), "id_token": "unverified-untrusted"}
        )

    result = ProviderClient(config, transport=httpx.MockTransport(handle)).tokens(
        code="test-code", verifier="v" * 64
    )
    assert "id_token" not in result
    assert len(requests) == 1 and requests[0].method == "POST"
    assert str(requests[0].url) == ProviderClient(config).token_url


@pytest.mark.parametrize(
    "fault",
    [
        "missing_scope",
        "bool_expiry",
        "long_expiry",
        "missing_refresh",
        "bad_type",
        "newline_token",
    ],
)
def test_invalid_tokens_rejected(config, fault):
    data = token_response(config)
    changes = {
        "missing_scope": {"scope": "openid"},
        "bool_expiry": {"expires_in": True},
        "long_expiry": {"expires_in": 86401},
        "missing_refresh": {"refresh_token": None},
        "bad_type": {"token_type": "Basic"},
        "newline_token": {"access_token": "bad\nvalue"},
    }
    data.update(changes[fault])
    client = ProviderClient(
        config, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=data))
    )
    with pytest.raises(OAuthError):
        client.tokens(code="test-code", verifier="v" * 64)


@pytest.mark.parametrize("status", [301, 302, 307, 400, 401, 403, 429, 500])
def test_provider_errors_not_followed_retried_or_echoed(config, status):
    calls = []

    def handle(req):
        calls.append(req)
        return httpx.Response(
            status,
            headers={"Location": "https://evil.example/token"},
            text="secret-response",
        )

    with pytest.raises(OAuthError) as error:
        ProviderClient(config, transport=httpx.MockTransport(handle)).tokens(
            code="fake", verifier="v" * 64
        )
    assert "secret-response" not in str(error.value) and len(calls) == 1


@pytest.mark.parametrize("body", [b'{"x":1,"x":2}', b'{"x":NaN}', b"\xff", b"[" * 1100])
def test_invalid_json_rejected(body):
    with pytest.raises(OAuthError):
        strict_json(body)


def test_large_response_rejected(config):
    with pytest.raises(OAuthError, match="provider_response_too_large"):
        ProviderClient(
            config,
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, content=b"x" * (2 * 1024 * 1024 + 1))
            ),
        ).tokens(code="test-code", verifier="v" * 64)


def test_microsoft_binds_from_graph_not_token_claims():
    config = ProviderConfig(
        "microsoft", MS_CLIENT, "secret", str(uuid4()), "unused", MS_TENANT
    )
    client = ProviderClient(
        config,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"value": [{"id": MS_TENANT}]})
        ),
    )
    assert client.bind_account("opaque-access") == {"tenant_id": MS_TENANT}


@pytest.mark.parametrize(
    "rows", [[], [{"id": str(uuid4())}], [{"id": MS_TENANT}, {"id": MS_TENANT}]]
)
def test_microsoft_rejects_wrong_or_ambiguous_tenant(rows):
    config = ProviderConfig(
        "microsoft", MS_CLIENT, "secret", str(uuid4()), "unused", MS_TENANT
    )
    client = ProviderClient(
        config,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"value": rows})
        ),
    )
    with pytest.raises(OAuthError, match="tenant_mismatch"):
        client.bind_account("opaque-access")


@pytest.mark.parametrize("demo", [False, None, "true", 1])
def test_xero_rejects_live_or_unproven_demo_company(demo):
    tenant, conn = str(uuid4()), str(uuid4())
    config = ProviderConfig("xero", "X" * 32, "secret", str(uuid4()), "unused")

    def handle(req):
        if req.url.path == "/connections":
            return httpx.Response(
                200,
                json=[{"id": conn, "tenantId": tenant, "tenantType": "ORGANISATION"}],
            )
        assert req.headers["xero-tenant-id"] == tenant
        return httpx.Response(
            200,
            json={"Organisations": [{"OrganisationID": tenant, "IsDemoCompany": demo}]},
        )

    with pytest.raises(OAuthError, match="demo_company_required"):
        ProviderClient(config, transport=httpx.MockTransport(handle)).bind_account(
            "opaque-access"
        )


def test_xero_demo_binding_and_disconnect_only_connections_endpoint():
    tenant, conn = str(uuid4()), str(uuid4())
    config = ProviderConfig("xero", "X" * 32, "secret", str(uuid4()), "unused")
    requests = []

    def handle(req):
        requests.append(req)
        if req.method == "DELETE":
            assert req.url.path == "/connections/" + conn
            return httpx.Response(204)
        if req.url.path == "/connections":
            return httpx.Response(
                200,
                json=[{"id": conn, "tenantId": tenant, "tenantType": "ORGANISATION"}],
            )
        return httpx.Response(
            200,
            json={"Organisations": [{"OrganisationID": tenant, "IsDemoCompany": True}]},
        )

    client = ProviderClient(config, transport=httpx.MockTransport(handle))
    account = client.bind_account("opaque-access")
    assert account == {"tenant_id": tenant, "connection_id": conn}
    assert client.disconnect_remote("opaque-access", account) == "provider_disconnect"
    assert [r.method for r in requests] == ["GET", "GET", "DELETE"]


def test_xero_multiple_connections_require_explicit_future_selection():
    config = ProviderConfig("xero", "X" * 32, "secret", str(uuid4()), "unused")
    with pytest.raises(OAuthError, match="one_xero_connection_required"):
        ProviderClient(
            config,
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[{}, {}])),
        ).bind_account("opaque")


def test_microsoft_disconnect_has_no_broad_revocation_request():
    config = ProviderConfig(
        "microsoft", MS_CLIENT, "secret", str(uuid4()), "unused", MS_TENANT
    )

    def forbidden(req):
        raise AssertionError("No global signout or grant write allowed")

    assert (
        ProviderClient(
            config, transport=httpx.MockTransport(forbidden)
        ).disconnect_remote("opaque", {})
        == "local_disconnect"
    )


def test_expired_secret_blocks_new_authorization(config):
    expired = replace(config, secret_expires_on="2000-01-01")
    with pytest.raises(OAuthError, match="client_secret_expired"):
        ProviderClient(expired).authorization_url("a" * 43, "v" * 64)
