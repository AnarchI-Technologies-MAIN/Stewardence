import json
import secrets

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_http_methods, require_POST

from . import quickbooks_services as services
from .forms import SandboxReportForm
from .quickbooks_client import OAuthError
from .quickbooks_crypto import CredentialError

STATUS_PATH = "/integrations/quickbooks/connect/"
CALLBACK_PATH = "/integrations/quickbooks/callback/"


def clean_redirect(path=STATUS_PATH):
    response = HttpResponseRedirect(path)
    response.content = b""
    response["Cache-Control"] = "no-cache, no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


def access(request):
    return request.user, request.session.get("active_organization_id")


@login_required
@require_http_methods(["GET", "POST"])
@sensitive_variables()
def connect(request):
    user, org_id = access(request)
    if request.method == "POST" and request.POST.get("action") == "select_workspace":
        if len(request.POST.getlist("workspace_id")) != 1:
            raise PermissionDenied("Select one authorized workspace.")
        with services.authority(user, request.POST.get("workspace_id")) as selected:
            request.session["active_organization_id"] = str(selected)
            request.session.pop("quickbooks_nonce", None)
        return clean_redirect()
    if not org_id:
        choices = services.sandbox_workspace_choices(user)
        return render(
            request,
            "integrations/quickbooks.html",
            {"workspace_required": True, "sandbox_workspaces": choices},
        )
    try:
        status = services.connection_status(user, org_id)
        if request.method == "POST":
            nonce = request.session.get("quickbooks_nonce") or secrets.token_urlsafe(32)
            request.session["quickbooks_nonce"] = nonce
            return clean_redirect(services.begin(user, org_id, nonce))
    except (OAuthError, CredentialError):
        request.session["quickbooks_result"] = "unavailable"
        status = "Unavailable"
    return render(
        request,
        "integrations/quickbooks.html",
        {
            "connection_status": status,
            "result": request.session.pop("quickbooks_result", ""),
            "sandbox_enabled": settings.QUICKBOOKS_SANDBOX_ENABLED,
            "report_form": SandboxReportForm(),
        },
    )


# Deliberately no login_required redirect carrying callback query parameters.
@sensitive_variables()
def callback(request):
    if (
        request.method != "GET"
        or not request.is_secure()
        or not request.user.is_authenticated
    ):
        return clean_redirect()
    try:
        services.complete(
            *access(request),
            request.session.get("quickbooks_nonce", ""),
            request.GET,
        )
        request.session["quickbooks_result"] = "connected"
    except (OAuthError, CredentialError, PermissionDenied):
        request.session["quickbooks_result"] = "connection_failed"
    return clean_redirect()


@login_required
@require_POST
@sensitive_variables()
def disconnect(request):
    try:
        services.disconnect(*access(request))
        request.session["quickbooks_result"] = "disconnected"
    except (OAuthError, CredentialError):
        request.session["quickbooks_result"] = "disconnect_pending"
    return clean_redirect()


@login_required
@require_POST
@sensitive_variables()
def refresh(request):
    try:
        outcome = services.refresh(*access(request))
        request.session["quickbooks_result"] = (
            "token_refreshed" if outcome == "refreshed" else "token_still_valid"
        )
    except (OAuthError, CredentialError):
        request.session["quickbooks_result"] = "refresh_failed"
    return clean_redirect()


@login_required
@require_POST
@sensitive_variables()
def verify_company(request):
    try:
        services.verify_company_access(*access(request))
        request.session["quickbooks_result"] = "company_access_verified"
    except OAuthError as error:
        request.session["quickbooks_result"] = {
            "token_check_required": "company_check_token_required",
            "company_check_rate_limited": "company_check_rate_limited",
        }.get(error.code, "company_check_failed")
    except CredentialError:
        request.session["quickbooks_result"] = "company_check_failed"
    return clean_redirect()


@login_required
@require_POST
@sensitive_variables()
def export_report(request):
    user, org_id = access(request)
    status = services.connection_status(user, org_id)
    allowed = {*SandboxReportForm.base_fields, "csrfmiddlewaretoken"}
    if any(k not in allowed or len(request.POST.getlist(k)) != 1 for k in request.POST):
        raise PermissionDenied("Submit one report selection.")
    form = SandboxReportForm(request.POST)
    if form.is_valid():
        try:
            evidence = services.export_profit_and_loss(user, org_id, form.period)
        except OAuthError as error:
            message = {
                "token_check_required": "Check token validity, then retry this export.",
                "report_export_rate_limited": "Wait 60 seconds between report exports.",
                "invalid_report_response": (
                    "The report could not be validated. No export was produced."
                ),
            }.get(error.code, "The sandbox report could not be retrieved. Retry later.")
            form.add_error(None, message)
        except CredentialError:
            form.add_error(None, "The sandbox connection is unavailable.")
        else:
            response = HttpResponse(
                json.dumps(evidence, ensure_ascii=True, allow_nan=False).encode(
                    "utf-8"
                ),
                content_type="application/json",
            )
            response["Content-Disposition"] = (
                'attachment; filename="stewardence-sandbox-profit-and-loss.json"'
            )
            response["Cache-Control"] = "no-cache, no-store"
            response["Referrer-Policy"] = "no-referrer"
            response["X-Content-Type-Options"] = "nosniff"
            return response
    return render(
        request,
        "integrations/quickbooks.html",
        {
            "connection_status": status,
            "sandbox_enabled": settings.QUICKBOOKS_SANDBOX_ENABLED,
            "report_form": form,
        },
        status=400,
    )


def disconnected(request):
    # Intuit's navigation URL must not itself mutate credentials on a GET.
    return clean_redirect()


class QuickBooksBoundaryMiddleware:
    """Before SecurityMiddleware: sensitive callbacks never render HTML."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith("/integrations/quickbooks/"):
            return self.get_response(request)
        if request.path.rstrip("/") == CALLBACK_PATH.rstrip("/") and (
            request.path != CALLBACK_PATH
            or request.method != "GET"
            or not request.is_secure()
        ):
            return clean_redirect()
        if not settings.QUICKBOOKS_SANDBOX_ENABLED:
            if request.path == CALLBACK_PATH:
                return clean_redirect()
            response = HttpResponse("Integration unavailable.", status=404)
        else:
            response = self.get_response(request)
        if request.path == CALLBACK_PATH:
            # Covers framework errors, expired login, CSRF failures, and redirects.
            response = clean_redirect()
        response["Cache-Control"] = "no-cache, no-store"
        response["Referrer-Policy"] = "no-referrer"
        return response
