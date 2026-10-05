from django.urls import path

from .views import assessment_snapshot_detail_view

app_name = "assessments"

urlpatterns = [
    path("<uuid:snapshot_id>/", assessment_snapshot_detail_view, name="detail"),
]
