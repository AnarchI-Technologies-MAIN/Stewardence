from django.urls import path

from .views import (
    create_rule_view,
    delete_rule_action,
    detail_rule_view,
    duplicate_rule_action,
    edit_rule_view,
    list_rules_view,
    toggle_rule_action,
)

app_name = "policies"

urlpatterns = [
    path("", list_rules_view, name="list"),
    path("add/", create_rule_view, name="create"),
    path("<uuid:rule_id>/", detail_rule_view, name="detail"),
    path("<uuid:rule_id>/edit/", edit_rule_view, name="edit"),
    path("<uuid:rule_id>/duplicate/", duplicate_rule_action, name="duplicate"),
    path("<uuid:rule_id>/toggle/", toggle_rule_action, name="toggle"),
    path("<uuid:rule_id>/delete/", delete_rule_action, name="delete"),
]
