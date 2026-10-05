from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.assessments.snapshots import create_assessment_snapshot
from apps.audit.append import append_audit_event
from apps.audit.events import (
    EVENT_INVENTORY_CHANGED,
    EVENT_INVENTORY_CREATED,
)
from apps.organizations.models import OrganizationMember
from apps.policies.context import inventory_policy_context
from apps.policies.engine import PolicyResult, evaluate_policies
from apps.policies.packs.accounting import ACCOUNTING_RISK_PACK_V1
from apps.policies.risk import calculate_policy_risk
from apps.roi.engine_v2 import ROI_ENGINE_VERSION, calculate_roi
from apps.roi.forms import ROIForm

from .forms import InventoryItemForm
from .models import InventoryItem
from .provenance import (
    INVENTORY_FACT_FIELDS,
    inventory_provenance,
    normalized_declared_fields,
)

WRITE_ROLES = {
    OrganizationMember.Role.OWNER,
    OrganizationMember.Role.ADMIN,
    OrganizationMember.Role.ASSESSOR,
}


def _organization_id(request):
    organization_id = getattr(request, "organization_id", None)
    if organization_id is None:
        raise Http404("Choose a firm before opening its inventory.")
    return organization_id


def _membership(request):
    return get_object_or_404(
        OrganizationMember,
        user_id=request.user.id,
        organization_id=_organization_id(request),
    )


def _require_inventory_writer(request):
    membership = _membership(request)
    if membership.role not in WRITE_ROLES:
        raise PermissionDenied("Your role has read-only access to this inventory.")
    return membership


def _inventory_item(request, item_id):
    return get_object_or_404(
        InventoryItem.objects.select_related("product__vendor"),
        id=item_id,
        organization_id=_organization_id(request),
    )


@login_required
def inventory_list_view(request):
    organization_id = _organization_id(request)
    items = InventoryItem.objects.filter(
        organization_id=organization_id,
        archived_at__isnull=True,
    )
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    if query:
        items = items.filter(
            Q(display_name__icontains=query)
            | Q(vendor_name__icontains=query)
            | Q(business_owner__icontains=query)
            | Q(department__icontains=query)
        )
    if status in InventoryItem.Status.values:
        items = items.filter(status=status)
        items = items.filter(
            Q(declaration_contract="") | Q(declared_fields__contains=["status"])
        )
    membership = _membership(request)
    return render(
        request,
        "inventory/list.html",
        {
            "items": items,
            "query": query,
            "selected_status": status,
            "status_choices": InventoryItem.Status.choices,
            "can_write": membership.role in WRITE_ROLES,
        },
    )


@login_required
def inventory_detail_view(request, item_id):
    item = _inventory_item(request, item_id)
    if item.declaration_contract:
        return redirect("inventory:explicit-detail", item_id=item.id)
    membership = _membership(request)
    policy_evaluation = evaluate_policies(
        ACCOUNTING_RISK_PACK_V1.rules,
        inventory_policy_context(item),
    )
    risk_score = calculate_policy_risk(policy_evaluation)
    return render(
        request,
        "inventory/detail.html",
        {
            "item": item,
            "item_provenance": inventory_provenance(item),
            "can_write": membership.role in WRITE_ROLES,
            "policy_findings": tuple(
                result
                for result in policy_evaluation.results
                if result.result is not PolicyResult.NOT_APPLICABLE
            ),
            "risk_score": risk_score,
        },
    )


@login_required
@transaction.atomic
@require_http_methods(["GET", "POST"])
def inventory_roi_view(request, item_id):
    item = _inventory_item(request, item_id)
    if item.declaration_contract:
        from .explicit_views import unavailable

        return unavailable()
    result = None
    if request.method == "POST":
        form = ROIForm(request.POST)
        if form.is_valid():
            result = calculate_roi(form.to_inputs())
            if request.POST.get("action") == "save_snapshot":
                _require_inventory_writer(request)
                from apps.assessments.snapshots import ExplicitInventoryCaptureRequired

                try:
                    snapshot = create_assessment_snapshot(
                        organization_id=_organization_id(request),
                        created_by_id=request.user.id,
                        assessed_item_id=item.id,
                        roi_inputs=form.to_inputs(),
                        captured_at=timezone.now(),
                        roi_engine_version=ROI_ENGINE_VERSION,
                    )
                except ExplicitInventoryCaptureRequired:
                    form.add_error(
                        None,
                        "This firm has knowledge records that require a deliberate "
                        "evidence review. Use that review path before saving a new "
                        "assessment.",
                    )
                    return render(
                        request,
                        "inventory/roi.html",
                        {"item": item, "form": form, "roi_result": result},
                        status=409,
                    )
                return redirect("assessments:detail", snapshot_id=snapshot.id)
    else:
        form = ROIForm(
            initial={
                "monthly_subscription_cost": item.monthly_cost_display,
                "monthly_subscription_cost_provenance": "Customer supplied",
                "implementation_cost": "0.00",
                "implementation_cost_provenance": "Unknown",
                "implementation_amortization_months": 12,
                "implementation_amortization_months_provenance": ("Customer supplied"),
                "hours_saved_per_month": "0.00",
                "hours_saved_per_month_provenance": "Unknown",
                "loaded_hourly_rate": "0.00",
                "loaded_hourly_rate_provenance": "Unknown",
                "attributable_revenue": "0.00",
                "attributable_revenue_provenance": "Unknown",
                "avoided_monthly_cost": "0.00",
                "avoided_monthly_cost_provenance": "Unknown",
            }
        )
    return render(
        request,
        "inventory/roi.html",
        {"item": item, "form": form, "roi_result": result},
    )


@login_required
@transaction.atomic
@require_http_methods(["GET", "POST"])
def create_inventory_item_view(request):
    membership = _require_inventory_writer(request)
    if (
        getattr(settings, "CORE_EXPLICIT_INVENTORY_ENABLED", False)
        and membership.role == OrganizationMember.Role.OWNER
    ):
        from .explicit_views import explicit_inventory_view

        return explicit_inventory_view(request)
    if request.method == "POST":
        form = InventoryItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.organization_id = _organization_id(request)
            item.source_type = InventoryItem.SourceType.MANUAL
            item.declared_fields = list(INVENTORY_FACT_FIELDS)
            item.save()
            append_audit_event(
                organization_id=item.organization_id,
                actor_user_id=request.user.id,
                event_type=EVENT_INVENTORY_CREATED,
                entity_type="inventory_item",
                entity_id=item.id,
                data={"source_type": item.source_type},
            )
            messages.success(request, f"{item.display_name} was added to inventory.")
            return redirect("inventory:detail", item_id=item.id)
    else:
        form = InventoryItemForm()
    return render(request, "inventory/form.html", {"form": form, "mode": "Add"})


@login_required
@transaction.atomic
@require_http_methods(["GET", "POST"])
def edit_inventory_item_view(request, item_id):
    _require_inventory_writer(request)
    item = _inventory_item(request, item_id)
    if item.declaration_contract:
        from .explicit_views import explicit_inventory_view

        return explicit_inventory_view(request, item_id=item.id)
    if request.method == "POST":
        form = InventoryItemForm(request.POST, instance=item)
        if form.is_valid():
            changed_fields = sorted(form.changed_data)
            item = form.save(commit=False)
            item.declared_fields = sorted(
                set(item.declared_fields)
                | set(normalized_declared_fields(changed_fields))
            )
            item.save()
            append_audit_event(
                organization_id=item.organization_id,
                actor_user_id=request.user.id,
                event_type=EVENT_INVENTORY_CHANGED,
                entity_type="inventory_item",
                entity_id=item.id,
                data={
                    "change": "edited",
                    "fields": changed_fields,
                },
            )
            messages.success(request, f"{item.display_name} was updated.")
            return redirect("inventory:detail", item_id=item.id)
    else:
        form = InventoryItemForm(instance=item)
    return render(request, "inventory/form.html", {"form": form, "mode": "Edit"})


@login_required
@require_POST
@transaction.atomic
def archive_inventory_item_action(request, item_id):
    _require_inventory_writer(request)
    item = _inventory_item(request, item_id)
    if item.declaration_contract:
        from .explicit_views import unavailable

        return unavailable()
    item.archived_at = timezone.now()
    item.declared_fields = sorted(set(item.declared_fields) | {"archived_at"})
    item.save(update_fields=("archived_at", "declared_fields", "updated_at"))
    append_audit_event(
        organization_id=item.organization_id,
        actor_user_id=request.user.id,
        event_type=EVENT_INVENTORY_CHANGED,
        entity_type="inventory_item",
        entity_id=item.id,
        data={"change": "archived"},
    )
    messages.success(request, f"{item.display_name} was archived.")
    return redirect("inventory:list")
