"""Owner-preview transports. Fixed endpoints, bounded reads, no business writes.

Microsoft OAuth grants API access; it is not a Stewardence login mechanism.
Tenant identity is established by Graph /organization, never decoded JWT claims.
"""

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urlencode
from uuid import UUID

import httpx
from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from .quickbooks_client import OAuthError
from .quickbooks_crypto import load_private_json

PROVIDERS = ("microsoft", "xero")
MS_CLIENT = "d6051326-8d93-4abf-b544-5bb2e9eb6e2f"
MS_TENANT = "9739bc34-9cd9-4775-84f4-681531b8efcf"
SCOPES = {
    "microsoft": (
        "openid",
        "profile",
        "offline_access",
        "User.Read",
        "Directory.Read.All",
    ),
    "xero": (
        "offline_access",
        "accounting.settings.read",
        "accounting.reports.profitandloss.read",
    ),
}


def require(ok, code="invalid_provider_response"):
    if not ok:
        raise OAuthError(code)


def identifier(value):
    try:
        parsed = str(UUID(value))
        require(parsed == value.lower())
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise OAuthError("invalid_provider_identifier") from None


def opaque(value, limit=16384):
    require(
        isinstance(value, str)
        and re.fullmatch(r"[\x21-\x7e]{1," + str(limit) + "}", value),
        "invalid_credential_value",
    )
    return value


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def invalid(_):
        raise ValueError

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, RecursionError, UnicodeError):
        raise OAuthError("invalid_provider_response") from None


@dataclass(frozen=True)
class ProviderConfig:
    provider: str
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    owner_user_id: str
    redirect_uri: str
    tenant_id: str = ""
    secret_expires_on: str = ""

    @classmethod
    @sensitive_variables()
    def load(cls, provider):
        require(provider in PROVIDERS, "unsupported_provider")
        require(
            not settings.DEBUG
            and getattr(settings, provider.upper() + "_PREVIEW_ENABLED", False),
            "disabled",
        )
        data = load_private_json(getattr(settings, provider.upper() + "_CLIENT_FILE"))
        redirect = "https://www.stewardence.com/integrations/" + provider + "/callback/"
        require(
            data.get("schema") == "stewardence.provider-preview-credentials.v1"
            and data.get("provider") == provider
            and data.get("redirect_uri") == redirect
            and data.get("scopes") == list(SCOPES[provider]),
            "invalid_provider_configuration",
        )
        owner = identifier(data.get("owner_user_id"))
        client = opaque(data.get("client_id"), 128)
        secret = opaque(data.get("client_secret"), 4096)
        tenant = ""
        if provider == "microsoft":
            tenant = identifier(data.get("tenant_id"))
            try:
                valid_expiry = bool(
                    date.fromisoformat(data["client_secret_expires_on"])
                )
            except (ValueError, KeyError, TypeError):
                valid_expiry = False
            require(
                tenant == MS_TENANT
                and client == MS_CLIENT
                and valid_expiry
                and data.get("mode") == "owner_tenant_preview",
                "invalid_provider_configuration",
            )
        else:
            require(data.get("require_demo_company") is True, "demo_company_required")
        return cls(
            provider,
            client,
            secret,
            owner,
            redirect,
            tenant,
            data.get("client_secret_expires_on", ""),
        )


class ProviderClient:
    def __init__(self, config, *, transport=None):
        self.config = config
        self.transport = transport

    @property
    def token_url(self):
        if self.config.provider == "microsoft":
            return (
                "https://login.microsoftonline.com/"
                + identifier(self.config.tenant_id)
                + "/oauth2/v2.0/token"
            )
        return "https://identity.xero.com/connect/token"

    def credential_current(self):
        if self.config.secret_expires_on:
            require(
                date.today() < date.fromisoformat(self.config.secret_expires_on),
                "client_secret_expired",
            )

    def authorization_url(self, state, verifier):
        self.credential_current()
        require(
            re.fullmatch(r"[A-Za-z0-9_-]{43}", state) is not None,
            "invalid_authorization_state",
        )
        params = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "scope": " ".join(SCOPES[self.config.provider]),
            "state": state,
        }
        if self.config.provider == "microsoft":
            opaque(verifier, 128)
            params.update(
                response_mode="query",
                code_challenge_method="S256",
                code_challenge=base64.urlsafe_b64encode(
                    hashlib.sha256(verifier.encode()).digest()
                )
                .decode()
                .rstrip("="),
            )
            url = (
                "https://login.microsoftonline.com/"
                + identifier(self.config.tenant_id)
                + "/oauth2/v2.0/authorize"
            )
        else:
            # Existing Xero registration is a confidential Web app, not a PKCE app.
            url = "https://login.xero.com/identity/connect/authorize"
        return url + "?" + urlencode(params)

    @sensitive_variables()
    def _request(self, method, url, *, expected=200, **kwargs):
        # URLs only originate in the fixed operation methods below. No redirects,
        # environment proxies, automatic retries or diagnostic payload logging.
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10, connect=5),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                with client.stream(method, url, **kwargs) as response:
                    if response.status_code != expected:
                        if response.status_code == 401:
                            raise OAuthError("reconnect_required")
                        if response.status_code == 429 or response.status_code >= 500:
                            raise OAuthError("provider_temporarily_unavailable")
                        raise OAuthError("provider_rejected_request")
                    raw = bytearray()
                    for chunk in response.iter_bytes(chunk_size=32768):
                        raw.extend(chunk)
                        require(
                            len(raw) <= 2 * 1024 * 1024, "provider_response_too_large"
                        )
                    if expected == 204:
                        return None
                    return strict_json(raw)
        except httpx.HTTPError:
            raise OAuthError("provider_temporarily_unavailable") from None

    @sensitive_variables()
    def tokens(self, *, code=None, verifier=None, refresh_token=None):
        self.credential_current()
        require(bool(code) != bool(refresh_token), "invalid_token_request")
        data = {"grant_type": "authorization_code" if code else "refresh_token"}
        if code:
            data.update(code=opaque(code, 4096), redirect_uri=self.config.redirect_uri)
        else:
            data["refresh_token"] = opaque(refresh_token)
        kwargs = {}
        if self.config.provider == "microsoft":
            data.update(
                client_id=self.config.client_id,
                client_secret=self.config.client_secret,
                scope=" ".join(SCOPES["microsoft"]),
            )
            if code:
                data["code_verifier"] = opaque(verifier, 128)
        else:
            kwargs["auth"] = (self.config.client_id, self.config.client_secret)
        result = self._request("POST", self.token_url, data=data, **kwargs)
        require(isinstance(result, dict), "invalid_token_response")
        require(
            str(result.get("token_type", "")).lower() == "bearer",
            "invalid_token_response",
        )
        expires = result.get("expires_in")
        require(type(expires) is int and 0 < expires <= 86400, "invalid_token_response")
        granted = result.get("scope")
        require(isinstance(granted, str), "invalid_token_response")
        grants = {
            s.removeprefix("https://graph.microsoft.com/") for s in granted.split()
        }
        required = set(SCOPES[self.config.provider]) - {
            "openid",
            "profile",
            "offline_access",
        }
        require(required <= grants, "required_scope_missing")
        refresh = result.get("refresh_token")
        if not refresh and refresh_token and self.config.provider == "microsoft":
            refresh = refresh_token
        # ID tokens are intentionally discarded. This is connection consent only.
        return {
            "access_token": opaque(result.get("access_token")),
            "refresh_token": opaque(refresh),
            "expires_in": expires,
        }

    @staticmethod
    def headers(token, tenant=None):
        result = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": "Bearer " + opaque(token),
        }
        if tenant:
            result["xero-tenant-id"] = identifier(tenant)
        return result

    @sensitive_variables()
    def bind_account(self, token):
        if self.config.provider == "microsoft":
            self.verify_account(token, {"tenant_id": self.config.tenant_id})
            return {"tenant_id": self.config.tenant_id}
        rows = self._request(
            "GET", "https://api.xero.com/connections", headers=self.headers(token)
        )
        require(
            isinstance(rows, list) and len(rows) == 1, "one_xero_connection_required"
        )
        row = rows[0]
        require(
            isinstance(row, dict) and row.get("tenantType") == "ORGANISATION",
            "invalid_provider_account",
        )
        account = {
            "tenant_id": identifier(row.get("tenantId")),
            "connection_id": identifier(row.get("id")),
        }
        self.verify_account(token, account)
        return account

    @sensitive_variables()
    def verify_account(self, token, account):
        if self.config.provider == "microsoft":
            require(
                account.get("tenant_id") == self.config.tenant_id, "tenant_mismatch"
            )
            data = self._request(
                "GET",
                "https://graph.microsoft.com/v1.0/organization",
                params={"$select": "id"},
                headers=self.headers(token),
            )
            rows = data.get("value") if isinstance(data, dict) else None
            require(
                isinstance(rows, list)
                and len(rows) == 1
                and isinstance(rows[0], dict)
                and rows[0].get("id") == self.config.tenant_id
                and "@odata.nextLink" not in data,
                "tenant_mismatch",
            )
            return
        tenant = identifier(account.get("tenant_id"))
        data = self._request(
            "GET",
            "https://api.xero.com/api.xro/2.0/Organisation",
            headers=self.headers(token, tenant),
        )
        rows = data.get("Organisations") if isinstance(data, dict) else None
        require(
            isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict),
            "invalid_provider_account",
        )
        require(identifier(rows[0].get("OrganisationID")) == tenant, "tenant_mismatch")
        require(rows[0].get("IsDemoCompany") is True, "demo_company_required")

    @sensitive_variables()
    def disconnect_remote(self, token, account):
        if self.config.provider == "microsoft":
            # Local credential removal is not a claim to revoke Entra admin consent.
            return "local_disconnect"
        connection_id = identifier(account.get("connection_id"))
        self._request(
            "DELETE",
            "https://api.xero.com/connections/" + connection_id,
            headers=self.headers(token),
            expected=204,
        )
        return "provider_disconnect"
