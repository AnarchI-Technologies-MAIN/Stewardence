"""Bounded sandbox OAuth transport. No accounting write API exists here."""

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

import httpx
from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from .quickbooks_crypto import CredentialError, load_private_json

DISCOVERY_URL = "https://developer.intuit.com/.well-known/openid_sandbox_configuration"
ENDPOINTS = {
    "authorization_endpoint": "https://appcenter.intuit.com/connect/oauth2",
    "token_endpoint": "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer",
    "revocation_endpoint": "https://developer.api.intuit.com/v2/oauth2/tokens/revoke",
}
SCOPE = "com.intuit.quickbooks.accounting"


class OAuthError(Exception):
    def __init__(self, code):
        # Only constant internal codes enter exceptions, never provider payloads.
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class OAuthConfig:
    client_id: str = field(repr=False)
    client_secret: str = field(repr=False)
    redirect_uri: str

    @classmethod
    @sensitive_variables()
    def load(cls):
        if not settings.QUICKBOOKS_SANDBOX_ENABLED:
            raise OAuthError("disabled")
        if settings.DEBUG:
            raise OAuthError("debug_forbidden")
        data = load_private_json(settings.QUICKBOOKS_CLIENT_FILE)
        redirect = settings.QUICKBOOKS_REDIRECT_URI
        parsed = urlsplit(redirect)
        if (
            data.get("environment") != "sandbox"
            or not isinstance(data.get("client_id"), str)
            or not isinstance(data.get("client_secret"), str)
            or not data["client_id"]
            or not data["client_secret"]
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.hostname not in settings.ALLOWED_HOSTS
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path != "/integrations/quickbooks/callback/"
        ):
            raise CredentialError("Invalid sandbox OAuth configuration")
        return cls(data["client_id"], data["client_secret"], redirect)


def validate_token(data):
    if not isinstance(data, dict):
        raise OAuthError("invalid_token_response")
    for name in ("access_token", "refresh_token"):
        value = data.get(name)
        if not isinstance(value, str) or not re.fullmatch(
            r"[\x21-\x7e]{1,8192}", value
        ):
            raise OAuthError("invalid_token_response")
    for name in ("expires_in", "x_refresh_token_expires_in"):
        value = data.get(name)
        if type(value) is not int or not 0 < value <= 366 * 86400:
            raise OAuthError("invalid_token_response")
    if str(data.get("token_type", "")).lower() != "bearer":
        raise OAuthError("invalid_token_response")
    return {
        name: data[name]
        for name in (
            "access_token",
            "refresh_token",
            "expires_in",
            "x_refresh_token_expires_in",
        )
    }


class QuickBooksClient:
    def __init__(self, config, *, transport=None):
        self.config = config
        self.transport = transport

    @sensitive_variables()
    def _request(
        self,
        method,
        url,
        *,
        revocation=False,
        raw_response=False,
        response_limit=65536,
        **kwargs,
    ):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(10.0, connect=5.0),
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                with client.stream(method, url, **kwargs) as response:
                    raw = bytearray()
                    for chunk in response.iter_bytes(chunk_size=65536):
                        raw.extend(chunk)
                        if len(raw) > response_limit:
                            raise OAuthError("provider_response_too_large")
                    if response.status_code == 200 and revocation:
                        return {}
                    if response.status_code == 200 and raw_response:
                        return bytes(raw)
                    try:
                        data = json.loads(raw)
                    except ValueError:
                        raise OAuthError("invalid_provider_response") from None
                    if response.status_code != 200:
                        if (
                            isinstance(data, dict)
                            and data.get("error") == "invalid_grant"
                        ):
                            raise OAuthError("reconnect_required")
                        if response.status_code == 429 or response.status_code >= 500:
                            raise OAuthError("provider_temporarily_unavailable")
                        raise OAuthError("provider_rejected_request")
                    return data
        except httpx.HTTPError:
            raise OAuthError("provider_temporarily_unavailable") from None

    def discover(self):
        data = self._request(
            "GET", DISCOVERY_URL, headers={"Accept": "application/json"}
        )
        if not isinstance(data, dict) or any(
            data.get(k) != v for k, v in ENDPOINTS.items()
        ):
            # Fail closed if Intuit changes endpoints; never send secrets to a URL
            # supplied by an unvalidated discovery response.
            raise OAuthError("discovery_endpoint_change")
        return data

    @sensitive_variables()
    def verify_company_access(self, realm_id, access_token):
        """Read one sandbox CompanyInfo response; retain no company fields."""
        if (
            not isinstance(realm_id, str)
            or not re.fullmatch(r"[0-9]{1,32}", realm_id)
            or not isinstance(access_token, str)
            or not re.fullmatch(r"[\x21-\x7e]{1,8192}", access_token)
        ):
            raise OAuthError("invalid_company_check")
        data = self._request(
            "GET",
            "https://sandbox-quickbooks.api.intuit.com/v3/company/"
            + realm_id
            + "/companyinfo/"
            + realm_id,
            headers={
                "Accept": "application/json",
                "Authorization": "Bearer " + access_token,
            },
        )
        company = data.get("CompanyInfo") if isinstance(data, dict) else None
        if (
            not isinstance(company, dict)
            or "Fault" in data
            or not isinstance(company.get("Id"), str)
            or not re.fullmatch(r"[0-9]{1,32}", company["Id"])
            or not isinstance(company.get("CompanyName"), str)
            or not company["CompanyName"].strip()
        ):
            raise OAuthError("invalid_company_response")
        # CompanyInfo.Id is an entity ID, not an independent realm assertion.
        return None

    @sensitive_variables()
    def profit_and_loss(self, realm_id, access_token, period):
        from .quickbooks_reports import ReportPeriod

        if (
            not isinstance(period, ReportPeriod)
            or not isinstance(realm_id, str)
            or not re.fullmatch(r"[0-9]{1,32}", realm_id)
            or not isinstance(access_token, str)
            or not re.fullmatch(r"[\x21-\x7e]{1,8192}", access_token)
        ):
            raise OAuthError("invalid_report_request")
        return self._request(
            "GET",
            "https://sandbox-quickbooks.api.intuit.com/v3/company/"
            + realm_id
            + "/reports/ProfitAndLoss",
            params=period.parameters(),
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Authorization": "Bearer " + access_token,
            },
            raw_response=True,
            response_limit=2 * 1024 * 1024,
        )

    def authorization_url(self, state):
        data = self.discover()
        return (
            data["authorization_endpoint"]
            + "?"
            + urlencode(
                {
                    "client_id": self.config.client_id,
                    "redirect_uri": self.config.redirect_uri,
                    "response_type": "code",
                    "scope": SCOPE,
                    "state": state,
                }
            )
        )

    @sensitive_variables()
    def tokens(self, *, code=None, refresh_token=None):
        if (code is None) == (refresh_token is None):
            raise OAuthError("invalid_token_request")
        endpoints = self.discover()
        payload = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        if code is not None:
            payload = {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
            }
        result = self._request(
            "POST",
            endpoints["token_endpoint"],
            data=payload,
            auth=httpx.BasicAuth(self.config.client_id, self.config.client_secret),
            headers={"Accept": "application/json"},
        )
        return validate_token(result)

    @sensitive_variables()
    def revoke(self, refresh_token):
        endpoints = self.discover()
        self._request(
            "POST",
            endpoints["revocation_endpoint"],
            json={"token": refresh_token},
            auth=httpx.BasicAuth(self.config.client_id, self.config.client_secret),
            headers={"Accept": "application/json"},
            revocation=True,
        )
