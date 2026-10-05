from django.urls import path

from .views import (
    activate_workspace_action,
    setup_organization_review_view,
    setup_organization_start_view,
    setup_organization_view,
    workspace_selection_view,
)

app_name = "organizations"

urlpatterns = [
    path(
        "",
        workspace_selection_view,
        name="workspace-selection",
    ),
    path(
        "activate/",
        activate_workspace_action,
        name="workspace-activate",
    ),
    path(
        "new/",
        setup_organization_view,
        name="setup",
    ),
    path(
        "new/start/",
        setup_organization_start_view,
        name="setup-start",
    ),
    path(
        "new/review/",
        setup_organization_review_view,
        name="setup-review",
    ),
]
