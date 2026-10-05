from django.urls import path

from . import provider_views
from . import quickbooks_views as views

app_name = "integrations"
urlpatterns = [
    path(
        "quickbooks/export-report/",
        views.export_report,
        name="quickbooks-export-report",
    ),
    path("quickbooks/connect/", views.connect, name="quickbooks-connect"),
    path("quickbooks/callback/", views.callback, name="quickbooks-callback"),
    path("quickbooks/disconnect/", views.disconnect, name="quickbooks-disconnect"),
    path(
        "quickbooks/disconnected/", views.disconnected, name="quickbooks-disconnected"
    ),
    path("quickbooks/refresh/", views.refresh, name="quickbooks-refresh"),
    path(
        "quickbooks/verify-company/",
        views.verify_company,
        name="quickbooks-verify-company",
    ),
]


for provider in ("microsoft", "xero"):
    urlpatterns += [
        path(
            provider + "/connect/",
            provider_views.connect,
            {"provider": provider},
            name=provider + "-connect",
        ),
        path(
            provider + "/callback/",
            provider_views.callback,
            {"provider": provider},
            name=provider + "-callback",
        ),
    ]
    for operation in ("refresh", "verify-account", "disconnect", "forget-local"):
        urlpatterns.append(
            path(
                provider + "/" + operation + "/",
                provider_views.operation,
                {"provider": provider, "operation": operation},
                name=provider + "-" + operation,
            )
        )
