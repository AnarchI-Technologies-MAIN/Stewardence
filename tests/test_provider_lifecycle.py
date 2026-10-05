import base64
import json
from datetime import timedelta
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import QueryDict
from django.utils import timezone

from apps.accounts.models import User
from apps.integrations import provider_services as service
from apps.integrations.models import ProviderAttempt, ProviderConnection, ProviderEvent
from apps.integrations.provider_client import MS_CLIENT, MS_TENANT, SCOPES
from apps.integrations.provider_crypto import decrypt
from apps.integrations.quickbooks_client import OAuthError
from apps.integrations.quickbooks_crypto import CredentialError
from apps.organizations.models import Organization, OrganizationMember

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture(params=["microsoft", "xero"])
def setup(request, settings, tmp_path, monkeypatch):
    if connection.vendor == "sqlite":
        monkeypatch.setattr(
            "agentledger.tenancy.context._set_local_context", lambda *a, **k: None
        )
    provider = request.param
    user = User.objects.create_user("preview-owner@example.com")
    org = Organization.objects.create(name="Provider qualification")
    OrganizationMember.objects.create(user=user, organization=org, role="owner")
    settings.DEBUG = False
    settings.ALLOWED_HOSTS = ["testserver", "www.stewardence.com"]
    setattr(settings, provider.upper() + "_PREVIEW_ENABLED", True)
    data = {
        "schema": "stewardence.provider-preview-credentials.v1",
        "provider": provider,
        "client_id": MS_CLIENT if provider == "microsoft" else "X" * 32,
        "client_secret": "fake-secret-test-only",
        "owner_user_id": str(user.id),
        "redirect_uri": f"https://www.stewardence.com/integrations/{provider}/callback/",
        "scopes": list(SCOPES[provider]),
        "tenant_id": MS_TENANT,
        "client_secret_expires_on": "2099-01-01",
        "mode": "owner_tenant_preview",
        "require_demo_company": True,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    setattr(settings, provider.upper() + "_CLIENT_FILE", str(path))
    key = tmp_path / "key.json"
    key.write_text(
        json.dumps(
            {
                "schema": "stewardence.provider-preview-keyring.v1",
                "active_key_id": "test",
                "keys": {"test": base64.b64encode(b"x" * 32).decode()},
            }
        )
    )
    key.chmod(0o600)
    settings.PROVIDER_PREVIEW_KEY_FILE = str(key)
    fake = Mock()
    fake.authorization_url.side_effect = lambda state, verifier: (
        "https://fixed.example/authorize?state=" + state
    )
    fake.tokens.return_value = {
        "access_token": "fake-access",
        "refresh_token": "fake-refresh",
        "expires_in": 3600,
    }
    fake.bind_account.return_value = {
        "tenant_id": MS_TENANT if provider == "microsoft" else str(uuid4()),
        "connection_id": str(uuid4()),
    }
    monkeypatch.setattr(service, "ProviderClient", lambda config: fake)
    return user, org, provider, fake


def start(setup):
    user, org, provider, _ = setup
    url = service.begin(user, org.id, provider, "a" * 43)
    state = parse_qs(urlsplit(url).query)["state"][0]
    return QueryDict("state=" + state + "&code=fake-code")


def connected(setup):
    user, org, provider, _ = setup
    service.complete(user, org.id, provider, "a" * 43, start(setup))
    return ProviderConnection.objects.get()


def test_connect_refresh_verify_disconnect(setup):
    user, org, provider, fake = setup
    obj = connected(setup)
    assert obj.status == "connected" and "fake-access" not in obj.encrypted_credentials
    assert ProviderAttempt.objects.get().encrypted_verifier == ""
    assert decrypt(obj, obj.encrypted_credentials)["access_token"] == "fake-access"
    service.verify_account(user, org.id, provider)
    assert ProviderEvent.objects.filter(kind="account_access_verified").count() == 1
    obj.access_expires_at = timezone.now() - timedelta(seconds=1)
    obj.save()
    fake.tokens.return_value = {**fake.tokens.return_value, "refresh_token": "rotated"}
    assert service.refresh(user, org.id, provider) == "token_refreshed"
    obj.refresh_from_db()
    assert decrypt(obj, obj.encrypted_credentials)["refresh_token"] == "rotated"
    outcome = service.disconnect(user, org.id, provider)
    obj.refresh_from_db()
    assert obj.status == "disconnected" and not obj.encrypted_credentials
    assert outcome == (
        "local_disconnected" if provider == "microsoft" else "provider_disconnected"
    )
    assert fake.disconnect_remote.call_count == (provider == "xero")


def test_replayed_callback_never_exchanges_again(setup):
    user, org, provider, fake = setup
    query = start(setup)
    service.complete(user, org.id, provider, "a" * 43, query)
    with pytest.raises(OAuthError, match="invalid_authorization_state"):
        service.complete(user, org.id, provider, "a" * 43, query)
    assert fake.tokens.call_count == 1


@pytest.mark.parametrize(
    "fault", ["expired", "session", "state", "duplicate", "generation"]
)
def test_wrong_state_session_expiry_and_generation_fail_before_exchange(setup, fault):
    user, org, provider, fake = setup
    query = start(setup)
    nonce = "a" * 43
    if fault == "expired":
        ProviderAttempt.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    if fault == "session":
        nonce = "b" * 43
    if fault == "state":
        query = QueryDict("state=" + "b" * 43 + "&code=fake")
    if fault == "duplicate":
        query = QueryDict(query.urlencode() + "&code=another")
    if fault == "generation":
        ProviderConnection.objects.update(generation=999)
    with pytest.raises(OAuthError):
        service.complete(user, org.id, provider, nonce, query)
    fake.tokens.assert_not_called()


def test_failed_exchange_consumes_state_permanently(setup):
    user, org, provider, fake = setup
    query = start(setup)
    fake.tokens.side_effect = OAuthError("provider_rejected_request")
    with pytest.raises(OAuthError):
        service.complete(user, org.id, provider, "a" * 43, query)
    assert ProviderAttempt.objects.get().consumed_at is not None
    assert not ProviderConnection.objects.get().encrypted_credentials
    with pytest.raises(OAuthError, match="invalid_authorization_state"):
        service.complete(user, org.id, provider, "a" * 43, query)
    assert fake.tokens.call_count == 1


def test_wrong_provider_account_never_stored(setup):
    user, org, provider, fake = setup
    query = start(setup)
    fake.bind_account.side_effect = OAuthError("tenant_mismatch")
    with pytest.raises(OAuthError):
        service.complete(user, org.id, provider, "a" * 43, query)
    assert ProviderAttempt.objects.get().consumed_at is not None
    assert ProviderConnection.objects.get().status == "disconnected"


def test_role_removal_denies_all_provider_operations(setup):
    user, org, provider, fake = setup
    connected(setup)
    OrganizationMember.objects.filter(user=user).update(role="viewer")
    for action in (
        service.refresh,
        service.verify_account,
        service.disconnect,
        service.status,
    ):
        with pytest.raises(PermissionDenied):
            action(user, org.id, provider)
    fake.verify_account.assert_not_called()


def test_unallowlisted_owner_and_foreign_workspace_denied(setup):
    user, org, provider, _ = setup
    other = User.objects.create_user("other@example.com")
    foreign = Organization.objects.create(name="Foreign")
    OrganizationMember.objects.create(user=other, organization=foreign, role="owner")
    with pytest.raises(PermissionDenied):
        service.begin(other, foreign.id, provider, "a" * 43)
    with pytest.raises(PermissionDenied):
        service.begin(user, foreign.id, provider, "a" * 43)


def test_crypto_binds_provider_workspace_actor_and_purpose(setup):
    obj = connected(setup)
    encrypted = obj.encrypted_credentials
    for field in ("provider", "organization_id", "connected_by_id"):
        original = getattr(obj, field)
        setattr(obj, field, "other" if field == "provider" else uuid4())
        with pytest.raises(CredentialError):
            decrypt(obj, encrypted)
        setattr(obj, field, original)
    with pytest.raises(CredentialError):
        decrypt(obj, encrypted, "attempt:other")


def test_refresh_failure_commits_reconnect_state(setup):
    user, org, provider, fake = setup
    obj = connected(setup)
    obj.access_expires_at = timezone.now() - timedelta(seconds=1)
    obj.save()
    fake.tokens.side_effect = OAuthError("provider_temporarily_unavailable")
    with pytest.raises(OAuthError):
        service.refresh(user, org.id, provider)
    obj.refresh_from_db()
    assert obj.status == "reconnect"


def test_xero_rotated_token_survives_failed_disconnect(setup):
    user, org, provider, fake = setup
    if provider != "xero":
        pytest.skip("Xero remote disconnection only")
    obj = connected(setup)
    obj.access_expires_at = timezone.now() - timedelta(seconds=1)
    obj.save()
    fake.tokens.return_value = {
        **fake.tokens.return_value,
        "refresh_token": "rotated-before-failure",
    }
    fake.disconnect_remote.side_effect = OAuthError("provider_temporarily_unavailable")
    with pytest.raises(OAuthError):
        service.disconnect(user, org.id, provider)
    obj.refresh_from_db()
    assert obj.status == "revoking"
    assert (
        decrypt(obj, obj.encrypted_credentials)["refresh_token"]
        == "rotated-before-failure"
    )


def test_same_origin_forms_and_foreign_origin_csrf(setup):
    from django.test import Client

    user, org, provider, fake = setup
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()
    path = f"/integrations/{provider}/connect/"
    response = client.get(path, secure=True)
    assert response.status_code == 200 and response["Referrer-Policy"] == "same-origin"
    csrf = client.cookies["csrftoken"].value
    response = client.post(
        path,
        {"csrfmiddlewaretoken": csrf, "action": "authorize"},
        secure=True,
        HTTP_ORIGIN="https://foreign.example",
    )
    assert response.status_code == 403
    response = client.post(
        path,
        {"csrfmiddlewaretoken": csrf, "action": "authorize"},
        secure=True,
        HTTP_ORIGIN="https://testserver",
    )
    assert response.status_code == 302 and response["Location"].startswith(
        "https://fixed.example/"
    )


def test_local_recovery_is_explicit_and_does_not_claim_remote_revocation(setup):
    user, org, provider, fake = setup
    obj = connected(setup)
    with pytest.raises(OAuthError):
        service.forget_failed_connection(user, org.id, provider)
    obj.status = "revoking"
    obj.save()
    if provider == "microsoft":
        with pytest.raises(OAuthError):
            service.forget_failed_connection(user, org.id, provider)
        return
    service.forget_failed_connection(user, org.id, provider)
    obj.refresh_from_db()
    assert obj.status == "disconnected" and obj.encrypted_credentials == ""
    fake.disconnect_remote.assert_not_called()
    assert ProviderEvent.objects.filter(
        connection=obj, kind="local_disconnected_consent_unverified"
    ).exists()
