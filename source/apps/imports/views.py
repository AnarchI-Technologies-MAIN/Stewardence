from __future__ import annotations

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from apps.audit.append import append_audit_event
from apps.audit.events import (
    EVENT_INVENTORY_CREATED,
    EVENT_RECONCILIATION_ACCEPTED,
)
from apps.inventory.models import InventoryItem
from apps.inventory.provenance import normalized_declared_fields
from apps.organizations.models import OrganizationMember

from .forms import CsvUploadForm
from .models import ImportBatch, ImportRow
from .parsing import ImportFileError, parse_csv_upload, validate_row

WRITE_ROLES = {
    OrganizationMember.Role.OWNER,
    OrganizationMember.Role.ADMIN,
    OrganizationMember.Role.ASSESSOR,
}


def _organization_id(request):
    organization_id = getattr(request, "organization_id", None)
    if organization_id is None:
        raise PermissionDenied("Choose a firm before importing inventory.")
    return organization_id


def _require_writer(request):
    membership = get_object_or_404(
        OrganizationMember,
        user_id=request.user.id,
        organization_id=_organization_id(request),
    )
    if membership.role not in WRITE_ROLES:
        raise PermissionDenied("Your role has read-only access to this inventory.")


def _batch(request, batch_id, *, lock=False):
    batches = ImportBatch.objects
    if lock:
        batches = batches.select_for_update()
    return get_object_or_404(
        batches,
        id=batch_id,
        organization_id=_organization_id(request),
        created_by_id=request.user.id,
    )


def _editable_row_payload(request, row):
    prefix = f"row-{row.row_number}"
    return {
        "display_name": request.POST.get(f"{prefix}-display_name", ""),
        "vendor_name": request.POST.get(f"{prefix}-vendor_name", ""),
        "business_owner": request.POST.get(f"{prefix}-business_owner", ""),
        "department": request.POST.get(f"{prefix}-department", ""),
        "user_count": request.POST.get(f"{prefix}-user_count", ""),
        "business_purpose": request.POST.get(f"{prefix}-business_purpose", ""),
        "monthly_cost": request.POST.get(f"{prefix}-monthly_cost", ""),
        "seat_count": request.POST.get(f"{prefix}-seat_count", ""),
        "autonomy_level": request.POST.get(f"{prefix}-autonomy_level", ""),
        "human_approval": request.POST.get(f"{prefix}-human_approval", ""),
        "status": request.POST.get(f"{prefix}-status", ""),
    }


def _review_rows(rows):
    return [
        {
            "row": row,
            "monthly_cost": (
                Decimal(row.data.get("monthly_cost_cents", 0)) / Decimal(100)
            ),
        }
        for row in rows
    ]


@login_required
@require_http_methods(["GET", "POST"])
def upload_csv_view(request):
    _require_writer(request)
    if request.method == "POST":
        form = CsvUploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload = form.cleaned_data["spreadsheet"]
            try:
                parsed_rows = parse_csv_upload(upload)
            except ImportFileError as error:
                form.add_error("spreadsheet", str(error))
            else:
                with transaction.atomic():
                    batch = ImportBatch.objects.create(
                        organization_id=_organization_id(request),
                        created_by=request.user,
                        source_filename=upload.name[:255],
                        row_count=len(parsed_rows),
                        status=(
                            ImportBatch.Status.REVIEWING
                            if any(errors for _number, _data, errors in parsed_rows)
                            else ImportBatch.Status.READY
                        ),
                    )
                    ImportRow.objects.bulk_create(
                        [
                            ImportRow(
                                organization_id=_organization_id(request),
                                batch=batch,
                                row_number=row_number,
                                data=data,
                                errors=errors,
                            )
                            for row_number, data, errors in parsed_rows
                        ]
                    )
                return redirect("imports:review", batch_id=batch.id)
    else:
        form = CsvUploadForm()
    return render(request, "imports/upload.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def review_import_view(request, batch_id):
    _require_writer(request)
    with transaction.atomic():
        batch = _batch(request, batch_id, lock=request.method == "POST")
        if batch.status == ImportBatch.Status.IMPORTED:
            raise PermissionDenied("This import has already been completed.")
        rows = list(
            batch.rows.select_for_update()
            if request.method == "POST"
            else batch.rows.all()
        )
        if request.method == "POST":
            seen: set[tuple[str, str]] = set()
            has_errors = False
            for row in rows:
                data, errors = validate_row(_editable_row_payload(request, row))
                duplicate_key = (
                    str(data["display_name"]).casefold(),
                    str(data["vendor_name"]).casefold(),
                )
                if duplicate_key in seen:
                    errors.append("This software and vendor appear more than once.")
                seen.add(duplicate_key)
                row.data = data
                row.errors = errors
                row.save(update_fields=("data", "errors", "updated_at"))
                has_errors = has_errors or bool(errors)
            batch.status = (
                ImportBatch.Status.REVIEWING if has_errors else ImportBatch.Status.READY
            )
            batch.save(update_fields=("status", "updated_at"))
            if not has_errors:
                return redirect("imports:final", batch_id=batch.id)
            messages.error(request, "Correct the highlighted rows before continuing.")

    return render(
        request,
        "imports/review.html",
        {
            "batch": batch,
            "review_rows": _review_rows(rows),
            "status_choices": InventoryItem.Status.choices,
        },
    )


@login_required
def final_review_view(request, batch_id):
    _require_writer(request)
    batch = _batch(request, batch_id)
    rows = list(batch.rows.all())
    if batch.status != ImportBatch.Status.READY or any(row.errors for row in rows):
        messages.error(
            request, "Finish correcting the spreadsheet before final review."
        )
        return redirect("imports:review", batch_id=batch.id)
    total_cost_cents = sum(row.data["monthly_cost_cents"] for row in rows)
    departments = {row.data["department"] for row in rows if row.data["department"]}
    return render(
        request,
        "imports/final.html",
        {
            "batch": batch,
            "item_count": len(rows),
            "department_count": len(departments),
            "total_monthly_cost": f"{Decimal(total_cost_cents) / Decimal(100):.2f}",
        },
    )


@login_required
@require_POST
def confirm_import_action(request, batch_id):
    _require_writer(request)
    with transaction.atomic():
        batch = _batch(request, batch_id, lock=True)
        rows = list(batch.rows.select_for_update())
        if batch.status != ImportBatch.Status.READY or any(row.errors for row in rows):
            raise PermissionDenied("This spreadsheet is not ready for final approval.")
        items = InventoryItem.objects.bulk_create(
            InventoryItem(
                organization_id=_organization_id(request),
                source_type=InventoryItem.SourceType.CSV,
                declared_fields=normalized_declared_fields(row.data),
                **row.data,
            )
            for row in rows
        )
        for item in items:
            append_audit_event(
                organization_id=item.organization_id,
                actor_user_id=request.user.id,
                event_type=EVENT_INVENTORY_CREATED,
                entity_type="inventory_item",
                entity_id=item.id,
                data={
                    "import_batch_id": str(batch.id),
                    "source_type": item.source_type,
                },
            )
        batch.status = ImportBatch.Status.IMPORTED
        batch.imported_count = len(rows)
        batch.save(update_fields=("status", "imported_count", "updated_at"))
        append_audit_event(
            organization_id=batch.organization_id,
            actor_user_id=request.user.id,
            event_type=EVENT_RECONCILIATION_ACCEPTED,
            entity_type="import_batch",
            entity_id=batch.id,
            data={"imported_count": str(batch.imported_count)},
        )
        batch.rows.all().delete()
    messages.success(request, f"Added {batch.imported_count} software items.")
    return redirect("inventory:list")


@login_required
@require_POST
def cancel_import_action(request, batch_id):
    _require_writer(request)
    with transaction.atomic():
        batch = _batch(request, batch_id, lock=True)
        if batch.status == ImportBatch.Status.IMPORTED:
            raise PermissionDenied("A completed import cannot be canceled.")
        batch.delete()
    messages.success(
        request, "The spreadsheet import was canceled. No software was added."
    )
    return redirect("inventory:list")
