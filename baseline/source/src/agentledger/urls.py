from django.shortcuts import redirect, render
from django.urls import include, path

from .downloads import download_view
from .health import healthz, readyz


def home_view(request):
    if request.user.is_authenticated:
        return redirect("organizations:workspace-selection")

    return render(
        request,
        "home.html",
    )


urlpatterns = [
    path("integrations/", include("apps.integrations.urls")),
    path(
        "healthz",
        healthz,
        name="healthz",
    ),
    path(
        "readyz",
        readyz,
        name="readyz",
    ),
    path(
        "download/",
        download_view,
        name="download",
    ),
    path(
        "accounts/",
        include("apps.accounts.urls"),
    ),
    path(
        "billing/",
        include("apps.billing.urls"),
    ),
    path(
        "workspaces/",
        include("apps.organizations.urls"),
    ),
    path(
        "inventory/",
        include("apps.inventory.urls"),
    ),
    path(
        "imports/",
        include("apps.imports.urls"),
    ),
    path(
        "assessments/",
        include("apps.assessments.urls"),
    ),
    path(
        "reports/",
        include("apps.reports.urls"),
    ),
    path(
        "rules/",
        include("apps.policies.urls"),
    ),
    path(
        "",
        home_view,
        name="home",
    ),
]
