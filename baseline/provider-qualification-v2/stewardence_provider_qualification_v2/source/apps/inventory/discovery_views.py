from __future__ import annotations

from django import forms
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from collector.contract import MAX_BUNDLE_BYTES, EvidenceError

from .discovery import ingest_bundle
from .models import DetectionEvidence, DiscoveryScan, InventoryItem
from .views import _organization_id, _require_inventory_writer


class EvidenceUploadForm(forms.Form):
    bundle = forms.FileField(label="Collector evidence bundle (.json)")


@login_required
@require_http_methods(["GET", "POST"])
def discovery_view(request):
    organization_id = _organization_id(request)
    form = EvidenceUploadForm(request.POST or None, request.FILES or None)
    uploaded_scan = None
    if request.method == "POST":
        _require_inventory_writer(request)
        if form.is_valid():
            uploaded = form.cleaned_data["bundle"]
            if uploaded.size > MAX_BUNDLE_BYTES:
                form.add_error("bundle", "Evidence bundle exceeds the size limit.")
            else:
                try:
                    uploaded_scan, _created = ingest_bundle(
                        organization_id=organization_id,
                        raw=uploaded.read(MAX_BUNDLE_BYTES + 1),
                        actor_user_id=request.user.id,
                    )
                except EvidenceError as error:
                    form.add_error("bundle", str(error))
    scans = list(
        DiscoveryScan.objects.filter(organization_id=organization_id)
        .prefetch_related(
            "observations__matched_product__vendor",
            "observations__inventory_item",
        )
        .order_by("-received_at", "-id")[:25]
    )
    seen_devices = set()
    scan_summaries = []
    for scan in scans:
        is_latest = scan.device_id not in seen_devices
        seen_devices.add(scan.device_id)
        observations = list(scan.observations.all())
        missing_items = ()
        if (
            is_latest
            and scan.bundle["coverage"].get("windows.installed_programs") == "complete"
        ):
            current_item_ids = {
                observation.inventory_item_id
                for observation in observations
                if observation.inventory_item_id is not None
            }
            historic_item_ids = DetectionEvidence.objects.filter(
                organization_id=organization_id,
                scan__device_id=scan.device_id,
                scan__received_at__lt=scan.received_at,
                reconciliation_status=(
                    DetectionEvidence.ReconciliationStatus.RECONCILED
                ),
            ).values_list("inventory_item_id", flat=True)
            missing_items = tuple(
                InventoryItem.objects.filter(
                    organization_id=organization_id,
                    id__in=set(historic_item_ids) - current_item_ids,
                ).order_by("display_name", "id")
            )
        scan_summaries.append(
            {
                "scan": scan,
                "observations": observations,
                "is_latest": is_latest,
                "missing_items": missing_items,
            }
        )
    return render(
        request,
        "inventory/discovery.html",
        {
            "form": form,
            "scan_summaries": scan_summaries,
            "uploaded_scan": uploaded_scan,
        },
    )
