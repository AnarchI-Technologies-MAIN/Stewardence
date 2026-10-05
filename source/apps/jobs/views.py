from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET
from apps.organizations.models import OrganizationMember
from .models import BackgroundJob, RecoveryReceipt
from .receipts import verify_recovery_receipt


@login_required
@require_GET
@transaction.atomic
def operations_dashboard(request):
    organization_id = getattr(request, "organization_id", None)
    if organization_id is None:
        raise Http404("Choose a firm before viewing operations")
    get_object_or_404(OrganizationMember, organization_id=organization_id, user_id=request.user.id)
    counts = list(BackgroundJob.objects.filter(organization_id=organization_id)
                  .values("status").annotate(count=Count("id")).order_by("status"))
    receipts = list(RecoveryReceipt.objects.select_related("job").filter(organization_id=organization_id)
                    .order_by("-created_at", "-id")[:50])
    integrity_ok = all(verify_recovery_receipt(receipt) for receipt in receipts)
    # Alerts derive from current held jobs, not historical failed attempts.
    alerts = list(BackgroundJob.objects.filter(organization_id=organization_id,
        status=BackgroundJob.Status.FAILED).order_by("-completed_at", "-id")[:25])
    response = render(request, "jobs/operations.html", {"counts":counts,
        "receipts":receipts if integrity_ok else [], "alerts":alerts,
        "integrity_ok":integrity_ok, "as_of":timezone.now()}, status=200 if integrity_ok else 503)
    response["Cache-Control"] = "private, no-store"
    return response
