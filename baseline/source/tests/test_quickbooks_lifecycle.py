import base64
import json
from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from django.db import connection
from django.http import QueryDict
from django.utils import timezone

from apps.accounts.models import User
from apps.integrations import quickbooks_services as service
from apps.integrations.models import (
    QuickBooksAttempt,
    QuickBooksConnection,
    QuickBooksEvent,
)
from apps.integrations.quickbooks_client import OAuthError
from apps.integrations.quickbooks_crypto import decrypt_credentials
from apps.organizations.models import Organization, OrganizationMember

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def setup(settings, tmp_path, monkeypatch):
    # SQLite exercises lifecycle only. Real set_config / RLS is retained for PG.
    if connection.vendor == "sqlite":
        monkeypatch.setattr(
            "agentledger.tenancy.context._set_local_context", lambda *a, **k: None
        )
    user = User.objects.create_user("oauth-owner@example.com")
    org = Organization.objects.create(name="Sandbox qualification")
    OrganizationMember.objects.create(user=user, organization=org, role="owner")
    settings.QUICKBOOKS_SANDBOX_ENABLED = True
    settings.QUICKBOOKS_SANDBOX_USER_IDS = [str(user.id)]
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["testserver", "www.stewardence.com"]
    settings.QUICKBOOKS_REDIRECT_URI = (
        "https://www.stewardence.com/integrations/quickbooks/callback/"
    )
    key = tmp_path / "key.json"
    key.write_text(
        json.dumps(
            {"primary": "test", "keys": {"test": base64.b64encode(b"x" * 32).decode()}}
        )
    )
    key.chmod(0o600)
    cfg = tmp_path / "client.json"
    cfg.write_text(
        json.dumps(
            {
                "environment": "sandbox",
                "client_id": "fake-client",
                "client_secret": "fake-secret",
            }
        )
    )
    cfg.chmod(0o600)
    settings.QUICKBOOKS_KEY_FILE = str(key)
    settings.QUICKBOOKS_CLIENT_FILE = str(cfg)
    fake = Mock()
    fake.authorization_url.side_effect = lambda state: (
        "https://appcenter.intuit.com/connect/oauth2?state=" + state
    )
    fake.tokens.return_value = {
        "access_token": "fake-access",
        "refresh_token": "fake-refresh",
        "expires_in": 3600,
        "x_refresh_token_expires_in": 8640000,
    }
    monkeypatch.setattr(service, "QuickBooksClient", lambda config: fake)
    return user, org, fake


def start(setup, nonce="a" * 43):
    user, org, fake = setup
    url = service.begin(user, org.id, nonce)
    state = parse_qs(urlsplit(url).query)["state"][0]
    return QueryDict("state=" + state + "&code=fake-code&realmId=12345")


def connected(setup):
    query = start(setup)
    service.complete(setup[0], setup[1].id, "a" * 43, query)
    return QuickBooksConnection.objects.get()


def test_complete_connect_refresh_disconnect_reconnect(setup):
    user, org, fake = setup
    obj = connected(setup)
    assert obj.status == "connected"
    assert "fake-access" not in obj.encrypted_credentials
    assert decrypt_credentials(obj)["realm_id"] == "12345"
    obj.access_expires_at = timezone.now() - timedelta(seconds=1)
    obj.save()
    fake.tokens.return_value = {**fake.tokens.return_value, "refresh_token": "rotated"}
    assert service.refresh(user, org.id) == "refreshed"
    obj.refresh_from_db()
    assert decrypt_credentials(obj)["refresh_token"] == "rotated"
    service.disconnect(user, org.id)
    fake.revoke.assert_called_once_with("rotated")
    obj.refresh_from_db()
    assert obj.status == "disconnected" and not obj.encrypted_credentials
    QuickBooksAttempt.objects.update(created_at=timezone.now() - timedelta(minutes=1))
    service.complete(user, org.id, "a" * 43, start(setup))
    obj.refresh_from_db()
    assert obj.status == "connected"
    assert QuickBooksEvent.objects.filter(kind="disconnected").count() == 1


def test_callback_replay_never_reexchanges_code(setup):
    query = start(setup)
    service.complete(setup[0], setup[1].id, "a" * 43, query)
    with pytest.raises(OAuthError, match="invalid_authorization_state"):
        service.complete(setup[0], setup[1].id, "a" * 43, query)
    assert setup[2].tokens.call_count == 1


@pytest.mark.parametrize("fault", ["expired", "session", "state", "duplicate"])
def test_invalid_callbacks_do_not_exchange(setup, fault):
    query = start(setup)
    nonce = "a" * 43
    if fault == "expired":
        QuickBooksAttempt.objects.update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )
    if fault == "session":
        nonce = "b" * 43
    if fault == "state":
        query = QueryDict("state=" + "b" * 43 + "&code=fake-code&realmId=12345")
    if fault == "duplicate":
        query = QueryDict(query.urlencode() + "&state=duplicate")
    with pytest.raises(OAuthError):
        service.complete(setup[0], setup[1].id, nonce, query)
    setup[2].tokens.assert_not_called()


def test_denial_consumes_state(setup):
    query = start(setup)
    denied = QueryDict("state=" + query["state"] + "&error=access_denied")
    with pytest.raises(OAuthError, match="authorization_denied"):
        service.complete(setup[0], setup[1].id, "a" * 43, denied)
    assert QuickBooksAttempt.objects.get().consumed_at is not None
    setup[2].tokens.assert_not_called()


def test_failed_exchange_still_consumes_state(setup):
    query = start(setup)
    setup[2].tokens.side_effect = OAuthError("provider_temporarily_unavailable")
    with pytest.raises(OAuthError):
        service.complete(setup[0], setup[1].id, "a" * 43, query)
    assert QuickBooksAttempt.objects.get().consumed_at is not None
    with pytest.raises(OAuthError, match="invalid_authorization_state"):
        service.complete(setup[0], setup[1].id, "a" * 43, query)
    assert setup[2].tokens.call_count == 1


def test_disconnect_failure_remains_paused_and_retryable(setup):
    obj = connected(setup)
    setup[2].revoke.side_effect = OAuthError("provider_temporarily_unavailable")
    with pytest.raises(OAuthError):
        service.disconnect(setup[0], setup[1].id)
    obj.refresh_from_db()
    assert obj.status == "revoking" and obj.encrypted_credentials
    with pytest.raises(OAuthError, match="connection_unavailable"):
        service.refresh(setup[0], setup[1].id)
    setup[2].revoke.side_effect = None
    service.disconnect(setup[0], setup[1].id)
    obj.refresh_from_db()
    assert obj.status == "disconnected"


@pytest.mark.parametrize("expired", [False, True])
def test_refresh_expiry_or_invalid_grant_commits_reconnect_required(setup, expired):
    obj = connected(setup)
    obj.access_expires_at = timezone.now() - timedelta(seconds=1)
    if expired:
        obj.refresh_expires_at = obj.access_expires_at
    obj.save()
    setup[2].tokens.reset_mock()
    setup[2].tokens.side_effect = OAuthError("reconnect_required")
    with pytest.raises(OAuthError, match="reconnect_required"):
        service.refresh(setup[0], setup[1].id)
    obj.refresh_from_db()
    assert obj.status == "reconnect"
    if expired:
        setup[2].tokens.assert_not_called()


def test_valid_token_is_not_unnecessarily_refreshed(setup):
    connected(setup)
    setup[2].tokens.reset_mock()
    assert service.refresh(setup[0], setup[1].id) == "still_valid"
    setup[2].tokens.assert_not_called()


def test_membership_removal_prevents_exchange(setup):
    from django.core.exceptions import PermissionDenied

    query = start(setup)
    OrganizationMember.objects.all().delete()
    with pytest.raises(PermissionDenied):
        service.complete(setup[0], setup[1].id, "a" * 43, query)
    setup[2].tokens.assert_not_called()


def test_nonallowlisted_actor_denied(setup, settings):
    from django.core.exceptions import PermissionDenied

    settings.QUICKBOOKS_SANDBOX_USER_IDS = []
    with pytest.raises(PermissionDenied):
        service.connection_status(setup[0], setup[1].id)


def test_callback_always_empty_redirect_and_no_sensitive_location(setup, client):
    client.force_login(setup[0])
    session = client.session
    session["active_organization_id"] = str(setup[1].id)
    session["quickbooks_nonce"] = "a" * 43
    session.save()
    query = start(setup)
    response = client.get(
        "/integrations/quickbooks/callback/?" + query.urlencode(), secure=True
    )
    assert response.status_code == 302 and response.content == b""
    assert response["Location"] == "/integrations/quickbooks/connect/"
    assert response["Cache-Control"] == "no-cache, no-store"
    assert QuickBooksConnection.objects.get().status == "connected"


def test_csrf_prevents_connect_and_disconnect(setup):
    from django.test import Client

    client = Client(enforce_csrf_checks=True)
    client.force_login(setup[0])
    for path in ["connect", "disconnect", "refresh", "verify-company"]:
        response = client.post("/integrations/quickbooks/" + path + "/", secure=True)
        assert response.status_code == 403
    setup[2].tokens.assert_not_called()
    setup[2].revoke.assert_not_called()
    setup[2].verify_company_access.assert_not_called()


def test_disabled_module_cannot_make_provider_calls(setup, settings, client):
    settings.QUICKBOOKS_SANDBOX_ENABLED = False
    response = client.get("/integrations/quickbooks/connect/", secure=True)
    assert response.status_code == 404
    setup[2].authorization_url.assert_not_called()


def test_disconnect_fences_pending_callback(setup):
    query = start(setup)
    service.disconnect(setup[0], setup[1].id)
    with pytest.raises(OAuthError, match="invalid_authorization_state"):
        service.complete(setup[0], setup[1].id, "a" * 43, query)
    setup[2].tokens.assert_not_called()


def test_nonowner_cannot_manage_connection(setup, settings):
    from django.core.exceptions import PermissionDenied

    connected(setup)
    other = User.objects.create_user("other-admin@example.com")
    OrganizationMember.objects.create(user=other, organization=setup[1], role="admin")
    settings.QUICKBOOKS_SANDBOX_USER_IDS += [str(other.id)]
    with pytest.raises(PermissionDenied):
        service.disconnect(other, setup[1].id)
    setup[2].revoke.assert_not_called()


def test_http_callback_does_not_exchange(setup, client):
    query = start(setup)
    response = client.get("/integrations/quickbooks/callback/?" + query.urlencode())
    assert response.status_code == 302 and response.content == b""
    setup[2].tokens.assert_not_called()


def test_connection_page_is_packaged_and_renders_without_credentials(setup, client):
    client.force_login(setup[0])
    session = client.session
    session["active_organization_id"] = str(setup[1].id)
    session.save()
    response = client.get("/integrations/quickbooks/connect/", secure=True)
    assert response.status_code == 200
    assert b"Connect sandbox company" in response.content
    assert b"csrfmiddlewaretoken" in response.content
    assert b"fake-secret" not in response.content
    assert b"fake-client" not in response.content
    assert response["Cache-Control"] == "no-cache, no-store"


def test_unpaid_sandbox_owner_can_select_workspace_without_oauth(setup, client):
    user, org, fake = setup
    client.force_login(user)
    response = client.get("/integrations/quickbooks/connect/", secure=True)
    assert response.status_code == 200
    assert b"Select your sandbox workspace" in response.content
    assert "active_organization_id" not in client.session
    response = client.post(
        "/integrations/quickbooks/connect/",
        {"action": "select_workspace", "workspace_id": str(org.id)},
        secure=True,
    )
    assert response.status_code == 302
    assert client.session["active_organization_id"] == str(org.id)
    fake.authorization_url.assert_not_called()
    assert not QuickBooksConnection.objects.exists()
    assert (
        client.get("/integrations/quickbooks/connect/", secure=True).status_code == 200
    )
    assert client.get("/workspaces/", secure=True)["Location"] == "/billing/portfolio/"


def test_sandbox_selection_rejects_foreign_workspace(setup, client):
    user, _, fake = setup
    foreign = Organization.objects.create(name="Other owner workspace")
    client.force_login(user)
    response = client.post(
        "/integrations/quickbooks/connect/",
        {"action": "select_workspace", "workspace_id": str(foreign.id)},
        secure=True,
    )
    assert response.status_code == 403
    assert "active_organization_id" not in client.session
    assert (
        foreign.name.encode()
        not in client.get("/integrations/quickbooks/connect/", secure=True).content
    )
    fake.authorization_url.assert_not_called()


def test_sandbox_selection_requires_allowlist(setup, client, settings):
    user, org, _ = setup
    client.force_login(user)
    settings.QUICKBOOKS_SANDBOX_USER_IDS = []
    assert (
        client.get("/integrations/quickbooks/connect/", secure=True).status_code == 403
    )
    assert (
        client.post(
            "/integrations/quickbooks/connect/",
            {"action": "select_workspace", "workspace_id": str(org.id)},
            secure=True,
        ).status_code
        == 403
    )
    assert "active_organization_id" not in client.session


def test_sandbox_selection_requires_csrf(setup):
    from django.test import Client

    user, org, _ = setup
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.post(
        "/integrations/quickbooks/connect/",
        {"action": "select_workspace", "workspace_id": str(org.id)},
        secure=True,
    )
    assert response.status_code == 403
    assert "active_organization_id" not in client.session


def test_sandbox_selection_rejects_admin_role(setup, client):
    user, org, _ = setup
    OrganizationMember.objects.filter(user=user, organization=org).update(role="admin")
    client.force_login(user)
    response = client.get("/integrations/quickbooks/connect/", secure=True)
    assert b"No owned workspace" in response.content
    assert (
        client.post(
            "/integrations/quickbooks/connect/",
            {"action": "select_workspace", "workspace_id": str(org.id)},
            secure=True,
        ).status_code
        == 403
    )


def test_company_probe_preserves_tokens_and_records_minimal_evidence(setup):
    obj = connected(setup)
    before = obj.encrypted_credentials
    service.verify_company_access(setup[0], setup[1].id)
    setup[2].verify_company_access.assert_called_once_with("12345", "fake-access")
    obj.refresh_from_db()
    assert obj.encrypted_credentials == before
    assert QuickBooksEvent.objects.filter(kind="company_access_verified").count() == 1
    assert QuickBooksEvent.objects.filter(kind="company_check_started").count() == 1
    with pytest.raises(OAuthError, match="company_check_rate_limited"):
        service.verify_company_access(setup[0], setup[1].id)
    assert setup[2].verify_company_access.call_count == 1


def test_company_probe_failure_commits_failed_event_without_success(setup):
    connected(setup)
    setup[2].verify_company_access.side_effect = OAuthError("provider_rejected_request")
    with pytest.raises(OAuthError):
        service.verify_company_access(setup[0], setup[1].id)
    assert QuickBooksEvent.objects.filter(kind="company_check_failed").count() == 1
    assert not QuickBooksEvent.objects.filter(kind="company_access_verified").exists()
    assert QuickBooksConnection.objects.get().status == "connected"


@pytest.mark.parametrize(
    "blocked",
    [
        "expired",
        "refresh_expired",
        "disconnected",
        "revoking",
        "reconnect",
        "foreign",
        "role",
        "allowlist",
        "disabled",
    ],
)
def test_company_probe_respects_connection_and_authority_boundaries(
    setup, settings, blocked
):
    from django.core.exceptions import PermissionDenied

    obj = connected(setup)
    org_id = setup[1].id
    if blocked == "expired":
        obj.access_expires_at = timezone.now()
    if blocked == "refresh_expired":
        obj.refresh_expires_at = timezone.now()
    if blocked in ["disconnected", "revoking", "reconnect"]:
        obj.status = blocked
    obj.save()
    if blocked == "foreign":
        org_id = Organization.objects.create(name="Foreign workspace").id
    if blocked == "role":
        OrganizationMember.objects.filter(user=setup[0]).update(role="admin")
    if blocked == "allowlist":
        settings.QUICKBOOKS_SANDBOX_USER_IDS = []
    if blocked == "disabled":
        settings.QUICKBOOKS_SANDBOX_ENABLED = False
    with pytest.raises((OAuthError, PermissionDenied)):
        service.verify_company_access(setup[0], org_id)
    setup[2].verify_company_access.assert_not_called()
    assert not QuickBooksEvent.objects.filter(kind="company_check_started").exists()


def test_company_probe_view_post_only_and_safe_success_message(setup, client):
    connected(setup)
    client.force_login(setup[0])
    session = client.session
    session["active_organization_id"] = str(setup[1].id)
    session.save()
    path = "/integrations/quickbooks/verify-company/"
    assert client.get(path, secure=True).status_code == 405
    setup[2].verify_company_access.assert_not_called()
    response = client.post(path, secure=True)
    assert response.status_code == 302 and response.content == b""
    page = client.get(response["Location"], secure=True)
    assert b"Sandbox company API access verified" in page.content
    assert b"fake-access" not in page.content


@pytest.mark.parametrize("expired", [False, True])
def test_token_check_ui_distinguishes_actual_renewal(setup, client, expired):
    obj = connected(setup)
    if expired:
        obj.access_expires_at = timezone.now()
        obj.save()
    client.force_login(setup[0])
    session = client.session
    session["active_organization_id"] = str(setup[1].id)
    session.save()
    response = client.post("/integrations/quickbooks/refresh/", secure=True)
    page = client.get(response["Location"], secure=True)
    expected = (
        b"Access token renewed with Intuit" if expired else b"No renewal was requested"
    )
    assert expected in page.content
    assert QuickBooksEvent.objects.filter(kind="token_refreshed").exists() == expired
