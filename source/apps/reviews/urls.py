from django.urls import path

from . import views
from .capture_views import capture_review

app_name = "reviews"
urlpatterns = [
    path("", views.history, name="history"),
    path("capture/", capture_review, name="capture"),
    path("compare/", views.comparison, name="comparison"),
    path("snapshots/<uuid:snapshot_id>/", views.snapshot_review, name="snapshot"),
    path(
        "snapshots/<uuid:snapshot_id>/proposals/",
        views.issue_proposals,
        name="issue-proposals",
    ),
    path("snapshots/<uuid:snapshot_id>/freeze/", views.freeze, name="freeze"),
    path("cards/<uuid:revision_id>/<int:card_index>/", views.decision, name="decision"),
    path("packs/<uuid:pack_id>/", views.pack_detail, name="pack-detail"),
    path(
        "packs/<uuid:pack_id>/stop-unused/",
        views.stop_unused_pack_view,
        name="stop-unused-pack",
    ),
    path(
        "packs/<uuid:pack_id>/request/", views.request_artifact, name="request-artifact"
    ),
]
