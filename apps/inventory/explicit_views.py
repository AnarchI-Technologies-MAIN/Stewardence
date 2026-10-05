"""Closed owner-only declaration path; legacy inventory stays independent."""

from uuid import uuid4

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.audit.append import append_audit_event
from apps.audit.events import EVENT_INVENTORY_CHANGED, EVENT_INVENTORY_CREATED
from apps.organizations.models import OrganizationMember

from .explicit_declarations import (
    CONTRACT,
    normalized_explicit_inventory_record,
    write_explicit_inventory,
)
from .explicit_forms import ExplicitInventoryForm
from .views import _inventory_item, _membership, _organization_id


def _owner(request):
    if _membership(request).role != OrganizationMember.Role.OWNER:
        raise PermissionDenied("Only the owner may record these declarations.")


def unavailable():
    response = HttpResponse(
        "This knowledge-recording capability is unavailable.", status=503
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["GET", "POST"])
def explicit_inventory_view(request, item_id=None):
    _owner(request)
    if not getattr(settings, "CORE_EXPLICIT_INVENTORY_ENABLED", False):
        return unavailable()
    item = _inventory_item(request, item_id) if item_id else None
    if item is not None and item.declaration_contract != CONTRACT:
        return unavailable()
    form = ExplicitInventoryForm(
        request.POST if request.method == "POST" else None, instance=item
    )
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                identity = write_explicit_inventory(
                    organization_id=_organization_id(request),
                    actor_id=request.user.id,
                    item_id=item.id if item else uuid4(),
                    form=form,
                )
                append_audit_event(
                    organization_id=_organization_id(request),
                    actor_user_id=request.user.id,
                    event_type=EVENT_INVENTORY_CHANGED
                    if item
                    else EVENT_INVENTORY_CREATED,
                    entity_type="inventory_item",
                    entity_id=identity,
                    data={"source_type": "manual", "declaration_contract": CONTRACT},
                )
        except DatabaseError:
            response = HttpResponse(
                (
                    "The declaration was not admitted. "
                    "Review availability and your current workspace access."
                ),
                status=409,
            )
            response["Cache-Control"] = "private, no-store"
            return response
        return redirect("inventory:explicit-detail", item_id=identity)
    return render(request, "inventory/explicit_form.html", {"form": form, "item": item})


@login_required
@require_http_methods(["GET"])
def explicit_inventory_detail(request, item_id):
    _owner(request)
    if not getattr(settings, "CORE_EXPLICIT_INVENTORY_ENABLED", False):
        return unavailable()
    item = _inventory_item(request, item_id)
    if item.declaration_contract != CONTRACT:
        return unavailable()
    record = normalized_explicit_inventory_record(item)
    rows = []
    for field, provenance in record["provenance"].items():
        if field in ("source_type", "product_id"):
            continue
        value = record[field]
        if field == "monthly_cost_cents" and value is not None:
            value = f"${value / 100:.2f} per month"
        elif isinstance(value, list):
            value = ", ".join(value) if value else "None declared"
        elif value is False:
            value = "No"
        elif value is True:
            value = "Yes"
        elif value is None:
            value = "Unknown"
        rows.append(
            {
                "label": field.replace("_", " ").capitalize(),
                "value": value,
                "provenance": provenance,
            }
        )
    return render(
        request,
        "inventory/explicit_detail.html",
        {"item": item, "record": record, "knowledge_rows": rows},
    )
