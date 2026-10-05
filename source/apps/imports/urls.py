from django.urls import path

from .views import (
    cancel_import_action,
    confirm_import_action,
    final_review_view,
    review_import_view,
    upload_csv_view,
)

app_name = "imports"

urlpatterns = [
    path("new/", upload_csv_view, name="upload"),
    path("<uuid:batch_id>/review/", review_import_view, name="review"),
    path("<uuid:batch_id>/final/", final_review_view, name="final"),
    path("<uuid:batch_id>/confirm/", confirm_import_action, name="confirm"),
    path("<uuid:batch_id>/cancel/", cancel_import_action, name="cancel"),
]
