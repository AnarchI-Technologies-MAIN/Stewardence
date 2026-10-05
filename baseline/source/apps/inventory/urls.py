from django.urls import path

from .discovery_views import discovery_view
from .views import (
    archive_inventory_item_action,
    create_inventory_item_view,
    edit_inventory_item_view,
    inventory_detail_view,
    inventory_list_view,
    inventory_roi_view,
)

app_name = "inventory"

urlpatterns = [
    path("discovery/", discovery_view, name="discovery"),
    path("", inventory_list_view, name="list"),
    path("add/", create_inventory_item_view, name="create"),
    path("<uuid:item_id>/", inventory_detail_view, name="detail"),
    path("<uuid:item_id>/roi/", inventory_roi_view, name="roi"),
    path("<uuid:item_id>/edit/", edit_inventory_item_view, name="edit"),
    path("<uuid:item_id>/archive/", archive_inventory_item_action, name="archive"),
]
