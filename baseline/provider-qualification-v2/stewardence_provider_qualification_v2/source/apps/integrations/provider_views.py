"""Owner preview pages; callbacks always return an empty, private redirect."""

import secrets

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_http_methods, require_POST

from . import provider_services as services
from .provider_client import PROVIDERS
from .quickbooks_client import OAuthError
from .quickbooks_crypto import CredentialError


def redirect(provider, target=None):
    response = HttpResponseRedirect(target or f"/integrations/{provider}/connect/")
    response.content = b""
    response["Cache-Control"] = "no-cache, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def access(request):
    return request.user, request.session.get("active_organization_id")


def single_fields(request, allowed):
    if any(k not in allowed or len(request.POST.getlist(k)) != 1 for k in request.POST):
        raise PermissionDenied("Submit one operation at a time.")


@login_required
@require_http_methods(["GET", "POST"])
@sensitive_variables()
def connect(request, provider):
    user, org_id = access(request)
    result_key = provider + "_preview_result"
    nonce_key = provider + "_preview_nonce"
    try:
        services.actor(user, provider)
        if request.method == "POST":
            single_fields(request, {"csrfmiddlewaretoken", "action", "workspace_id"})
            action = request.POST.get("action")
            if action == "select_workspace":
                with services.authority(
                    user, request.POST.get("workspace_id"), provider
                ) as selected:
                    request.session["active_organization_id"] = str(selected)
                    request.session.pop(nonce_key, None)
                return redirect(provider)
            if action != "authorize" or "workspace_id" in request.POST:
                raise PermissionDenied("Unknown operation.")
            nonce = request.session.get(nonce_key) or secrets.token_urlsafe(32)
            request.session[nonce_key] = nonce
            return redirect(provider, services.begin(user, org_id, provider, nonce))
        if not org_id:
            context = {
                "workspace_required": True,
                "workspaces": services.workspace_choices(user, provider),
            }
        else:
            context = services.status(user, org_id, provider)
        context.update(
            provider=provider,
            provider_name={"microsoft": "Microsoft", "xero": "Xero"}[provider],
            result=request.session.pop(result_key, ""),
        )
    except (OAuthError, CredentialError):
        return HttpResponse("Integration configuration unavailable.", status=503)
    return render(request, "integrations/provider_preview.html", context)


@sensitive_variables()
def callback(request, provider):
    if (
        request.method != "GET"
        or not request.is_secure()
        or not request.user.is_authenticated
    ):
        return redirect(provider)
    try:
        services.complete(
            *access(request),
            provider,
            request.session.get(provider + "_preview_nonce", ""),
            request.GET,
        )
        outcome = "Connected. Account boundary verified; automatic collection is off."
    except (OAuthError, CredentialError, PermissionDenied):
        outcome = "Connection was not completed. Review the account and retry."
    request.session[provider + "_preview_result"] = outcome
    return redirect(provider)


@login_required
@require_POST
@sensitive_variables()
def operation(request, provider, operation):
    single_fields(request, {"csrfmiddlewaretoken", "confirm_local_only"})
    try:
        if operation == "refresh":
            outcome = services.refresh(*access(request), provider)
            message = {
                "token_still_valid": "Access token remains valid; no renewal needed.",
                "token_refreshed": "Access token renewed successfully.",
            }[outcome]
        elif operation == "verify-account":
            services.verify_account(*access(request), provider)
            message = (
                "Authorized account access verified. No financial report was collected."
            )
        elif operation == "disconnect":
            outcome = services.disconnect(*access(request), provider)
            message = (
                "Local credentials removed. "
                "Entra admin consent remains until revoked in Microsoft."
                if outcome == "local_disconnected"
                else "Xero connection removed and local credentials cleared."
            )
        elif operation == "forget-local":
            if request.POST.get("confirm_local_only") != "yes":
                raise PermissionDenied("Confirm that provider consent remains.")
            services.forget_failed_connection(*access(request), provider)
            message = (
                "Local credentials removed. Provider revocation is unverified; "
                "remove this connection in Xero before reconnecting."
            )
        else:
            raise PermissionDenied("Unknown operation.")
    except (OAuthError, CredentialError):
        message = (
            "Operation did not complete. "
            "Check token validity and connection status before retrying."
        )
    request.session[provider + "_preview_result"] = message
    return redirect(provider)


class ProviderBoundaryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        provider = next(
            (p for p in PROVIDERS if request.path.startswith(f"/integrations/{p}/")),
            None,
        )
        if provider is None:
            return self.get_response(request)
        callback_path = f"/integrations/{provider}/callback/"
        is_callback = request.path.startswith(callback_path.rstrip("/"))
        if is_callback and (
            request.path != callback_path
            or request.method != "GET"
            or not request.is_secure()
        ):
            return redirect(provider)
        if not getattr(settings, provider.upper() + "_PREVIEW_ENABLED", False):
            response = (
                redirect(provider)
                if is_callback
                else HttpResponse("Integration unavailable.", status=404)
            )
        else:
            response = self.get_response(request)
        if is_callback:
            response = redirect(provider)
        response["Cache-Control"] = "no-cache, no-store"
        response["Referrer-Policy"] = "no-referrer" if is_callback else "same-origin"
        response["X-Content-Type-Options"] = "nosniff"
        return response
