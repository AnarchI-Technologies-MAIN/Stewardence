import logging

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from apps.integrations.logging import NoOAuthCallbackDiagnostics
from apps.integrations.provider_views import ProviderBoundaryMiddleware


@pytest.mark.parametrize("provider", ["microsoft", "xero"])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("status", [200, 403, 500])
def test_callback_always_private_empty_redirect(settings, provider, enabled, status):
    setattr(settings, provider.upper() + "_PREVIEW_ENABLED", enabled)
    request = RequestFactory().get(
        f"/integrations/{provider}/callback/?code=private", secure=True
    )
    response = ProviderBoundaryMiddleware(
        lambda req: HttpResponse("private", status=status)
    )(request)
    assert response.status_code == 302 and response.content == b""
    assert response["Location"] == f"/integrations/{provider}/connect/"
    assert response["Cache-Control"] == "no-cache, no-store"
    assert response["Referrer-Policy"] == "no-referrer"


@pytest.mark.parametrize("provider", ["microsoft", "xero"])
@pytest.mark.parametrize("fault", ["slash", "http", "post"])
def test_callback_wrong_shape_stops_before_framework(settings, provider, fault):
    setattr(settings, provider.upper() + "_PREVIEW_ENABLED", True)
    path = f"/integrations/{provider}/callback" + ("" if fault == "slash" else "/")
    factory = RequestFactory()
    request = (factory.post if fault == "post" else factory.get)(
        path + "?code=private", secure=fault != "http"
    )

    def forbidden(request):
        raise AssertionError("Callback reached downstream middleware")

    assert ProviderBoundaryMiddleware(forbidden)(request).status_code == 302


@pytest.mark.parametrize("provider", ["microsoft", "xero"])
def test_callback_logs_suppressed(provider):
    record = logging.LogRecord(
        "django.request",
        logging.ERROR,
        "",
        0,
        f"/integrations/{provider}/callback/?code=private",
        (),
        None,
    )
    assert not NoOAuthCallbackDiagnostics().filter(record)
