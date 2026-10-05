import logging

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from apps.integrations.logging import NoOAuthCallbackDiagnostics
from apps.integrations.quickbooks_views import QuickBooksBoundaryMiddleware


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("status", [200, 400, 403, 500])
def test_callback_errors_never_render_html(settings, enabled, status):
    settings.QUICKBOOKS_SANDBOX_ENABLED = enabled
    request = RequestFactory().get(
        "/integrations/quickbooks/callback/?code=private", secure=True
    )
    response = QuickBooksBoundaryMiddleware(
        lambda req: HttpResponse("private html", status=status)
    )(request)
    assert response.status_code == 302
    assert response.content == b""
    assert "private" not in response["Location"]


def test_insecure_callback_does_not_redirect_query_to_https(settings):
    settings.QUICKBOOKS_SANDBOX_ENABLED = True

    def forbidden(request):
        raise AssertionError("Insecure callback entered downstream middleware")

    request = RequestFactory().get("/integrations/quickbooks/callback/?code=private")
    response = QuickBooksBoundaryMiddleware(forbidden)(request)
    assert response.status_code == 302 and "?" not in response["Location"]


def test_callback_logs_are_suppressed():
    record = logging.LogRecord(
        "django.request", logging.ERROR, "", 0, "private", (), None
    )
    record.request = RequestFactory().get(
        "/integrations/quickbooks/callback/?code=private"
    )
    assert not NoOAuthCallbackDiagnostics().filter(record)


def test_callback_missing_slash_cannot_redirect_sensitive_query(settings):
    settings.QUICKBOOKS_SANDBOX_ENABLED = True

    def forbidden(request):
        raise AssertionError("Sensitive query reached CommonMiddleware redirect")

    request = RequestFactory().get(
        "/integrations/quickbooks/callback?code=private", secure=True
    )
    response = QuickBooksBoundaryMiddleware(forbidden)(request)
    assert response.status_code == 302 and "?" not in response["Location"]
