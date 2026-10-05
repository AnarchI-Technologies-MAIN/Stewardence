"""Owner-reviewed, signed preview; the database separately admits capture."""

from django import forms
from django.conf import settings
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.organizations.models import WorkflowProfile

from .views import owner_workspace

PREVIEW_SALT = "stewardence.core.capture.preview.v1"
PREVIEW_MAX_AGE = 900


class CaptureConfirmationForm(forms.Form):
    preview_token = forms.CharField(max_length=1_500_000, widget=forms.HiddenInput)
    confirm = forms.BooleanField(
        label="I reviewed these recorded answers and want to save this dated capture."
    )


def _display_records(frame):
    records = []
    for record in frame["inventory_records"]:
        fields = []
        for field, basis in record["provenance"].items():
            if field in {"product_id", "source_type"}:
                continue
            value = record[field]
            display = "Unknown"
            if basis == "Declared":
                display = str(value)
                if type(value) is bool:
                    display = "Yes" if value else "No"
                if type(value) is list:
                    display = ", ".join(value) if value else "None declared"
            fields.append(
                {
                    "label": field.replace("_", " ").capitalize(),
                    "basis": basis,
                    "display": display,
                }
            )
        records.append(
            {
                "name": record["display_name"],
                "as_of": record["declaration_as_of"],
                "fields": fields,
            }
        )

    return records


@owner_workspace
@require_http_methods(["GET", "POST"])
def capture_review(request):
    if not getattr(settings, "DELIBERATE_CAPTURE_ENABLED", False):
        return HttpResponse("Deliberate evidence capture is unavailable.", status=503)
    org, actor = request.organization_id, request.user.id
    if not WorkflowProfile.objects.filter(organization_id=org).exists():
        return redirect("organizations:workflow-profile")

    from apps.assessments.capture_admission import (
        issue_deliberate_capture,
        prepare_capture_preview,
    )

    frame = None
    error = None
    status = 200
    form = CaptureConfirmationForm(request.POST or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                frame = signing.loads(
                    form.cleaned_data["preview_token"],
                    salt=PREVIEW_SALT,
                    max_age=PREVIEW_MAX_AGE,
                )

                if (
                    type(frame) is not dict
                    or frame.get("organization_id") != str(org)
                    or frame.get("actor_id") != str(actor)
                ):
                    raise signing.BadSignature("Capture owner identity mismatch")

                with transaction.atomic():
                    snapshot = issue_deliberate_capture(
                        organization_id=org, actor_id=actor, reviewed_frame=frame
                    )

                return redirect("reviews:snapshot", snapshot_id=snapshot.id)

            except signing.BadSignature:
                frame = None

                error = (
                    "This review has expired or changed. "
                    "Open a fresh preview before saving."
                )

                status = 400

            except ValidationError, ValueError, DatabaseError:
                frame = None

                error = (
                    "This capture could not be admitted. Review the current answers, "
                    "workspace setup and work controls before retrying."
                )

                status = 409

        else:
            status = 400

    else:
        try:
            with transaction.atomic():
                frame = prepare_capture_preview(organization_id=org, actor_id=actor)

            form = CaptureConfirmationForm(
                initial={
                    "preview_token": signing.dumps(
                        frame, salt=PREVIEW_SALT, compress=True
                    )
                }
            )

        except ValidationError, ValueError, DatabaseError:
            error = (
                "A capture needs 1 to 100 deliberately reviewed tool records, "
                "a recorded workspace meaning and current access. Review your records "
                "and work controls before opening another preview."
            )

            status = 409

    return render(
        request,
        "reviews/capture.html",
        {
            "frame": frame,
            "records": _display_records(frame) if frame else [],
            "form": form,
            "error": error,
        },
        status=status,
    )
