from django import forms
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction, connection
from django.http import Http404
from django.shortcuts import get_object_or_404, render, redirect
from django.views.decorators.http import require_http_methods
from apps.jobs.contracts import validate_branch_settings
from .models import Organization, OrganizationMember, WorkflowProfile


class WorkflowProfileForm(forms.Form):
    profile = forms.ChoiceField(choices=WorkflowProfile._meta.get_field("profile").choices)
    name = forms.CharField(max_length=200)
    jurisdiction = forms.CharField(max_length=200, required=False)
    repository_ref = forms.CharField(max_length=200, required=False)
    environment = forms.CharField(max_length=200, required=False)

    def clean(self):
        data = super().clean()
        profile = data.get("profile")
        if not profile or "name" not in data:
            return data
        values = {key:data[key] for key in ("name", "jurisdiction", "repository_ref", "environment") if data.get(key)}
        try:
            data["admitted_settings"] = validate_branch_settings(profile, values)["settings"]
        except ValueError:
            raise forms.ValidationError("Settings do not match the selected profile or contain an invalid identifier.")
        return data


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def workflow_profile_view(request):
    organization_id = getattr(request, "organization_id", None)
    if organization_id is None:
        raise Http404("Choose a firm first")
    member = get_object_or_404(OrganizationMember, organization_id=organization_id, user_id=request.user.id)
    if member.role != OrganizationMember.Role.OWNER:
        raise PermissionDenied("Only the workspace owner can configure workflow meaning")
    # Serialize the initial decision so concurrent choices cannot reinterpret data.
    get_object_or_404(Organization, id=organization_id)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [f"workflow-profile:{organization_id}"])
    current = WorkflowProfile.objects.filter(organization_id=organization_id).first()
    if request.method == "POST" and current is not None:
        raise PermissionDenied("Changing a recorded profile requires a reviewed version transition")
    form = WorkflowProfileForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        WorkflowProfile.objects.create(organization_id=organization_id,
            created_by=request.user, profile=form.cleaned_data["profile"],
            settings=form.cleaned_data["admitted_settings"])
        return redirect("organizations:workflow-profile")
    response = render(request, "organizations/workflow_profile.html", {"form":form, "current":current})
    response["Cache-Control"] = "private, no-store"
    return response
