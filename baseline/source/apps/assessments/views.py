from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from .models import AssessmentSnapshot
from .snapshots import verify_snapshot


@login_required
def assessment_snapshot_detail_view(request, snapshot_id):
    organization_id = getattr(request, "organization_id", None)
    if organization_id is None:
        raise Http404("Choose a firm before opening an assessment.")
    snapshot = get_object_or_404(
        AssessmentSnapshot,
        id=snapshot_id,
        organization_id=organization_id,
    )
    return render(
        request,
        "assessments/detail.html",
        {"snapshot": snapshot, "hashes_valid": verify_snapshot(snapshot)},
    )
