from django.urls import path

from .views import (
    generate_report_action,
    report_detail_view,
    report_download_view,
)

app_name = "reports"

urlpatterns = [
    path(
        "from-assessment/<uuid:snapshot_id>/",
        generate_report_action,
        name="generate",
    ),
    path(
        "<uuid:report_id>/download/",
        report_download_view,
        name="download",
    ),
    path("<uuid:report_id>/", report_detail_view, name="detail"),
]
