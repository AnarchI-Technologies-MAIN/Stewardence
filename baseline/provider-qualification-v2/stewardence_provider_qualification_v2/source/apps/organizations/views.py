from __future__ import annotations

from apps.billing.models import Subscription

from uuid import UUID

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from agentledger.tenancy.context import identity_transaction

from .forms import OrganizationSetupForm, OrganizationStartForm
from .models import Organization, OrganizationMember
from .services import create_owned_workspace

_SETUP_DETAILS_KEY = "agentledger_setup_organization"
_SETUP_START_KEY = "agentledger_setup_start"


def _subscription_for_user(user):
    return (
        Subscription.objects
        .filter(billing_customer__user=user)
        .select_related("organization")
        .first()
    )


def _bind_subscription_to_owned_organization(user):
    """Recovery seam for legacy unbound paid accounts."""
    with transaction.atomic():
        subscription = (
            Subscription.objects
            .select_for_update()
            .filter(
                billing_customer__user=user,
                organization__isnull=True,
            )
            .first()
        )

        if subscription is None:
            return None

        if not subscription.grants_access:
            return None

        owned_memberships = list(
            OrganizationMember.objects
            .filter(
                user=user,
                role=OrganizationMember.Role.OWNER,
            )
            .select_related("organization")
            .order_by("created_at")
        )

        if len(owned_memberships) != 1:
            return None

        organization = owned_memberships[0].organization

        subscription.organization = organization
        subscription.save(
            update_fields=[
                "organization",
                "updated_at",
            ]
        )

        return organization.id


def _create_and_bind_owned_workspace(*, user, name, industry):
    """Create the paid workspace and bind its subscription atomically."""
    with transaction.atomic():
        subscription = (
            Subscription.objects
            .select_for_update()
            .filter(billing_customer__user=user)
            .first()
        )

        if subscription is None or not subscription.grants_access:
            raise PermissionDenied(
                "An active Stewardence subscription is required."
            )

        if subscription.organization_id is not None:
            raise PermissionDenied(
                "This subscription is already assigned to a workspace."
            )

        organization_id = create_owned_workspace(
            user_id=user.id,
            name=name,
            industry=industry,
        )

        subscription.organization_id = organization_id
        subscription.save(
            update_fields=[
                "organization",
                "updated_at",
            ]
        )

        return organization_id
@login_required
def workspace_selection_view(request):
    _bind_subscription_to_owned_organization(request.user)

    subscription = _subscription_for_user(request.user)

    memberships = []

    if (
        subscription is not None
        and subscription.grants_access
        and subscription.organization_id is not None
    ):
        with identity_transaction(request.user.id):
            memberships = list(
                OrganizationMember.objects.filter(
                    user_id=request.user.id,
                    organization_id=subscription.organization_id,
                )
                .select_related("organization")
                .order_by(
                    "organization__name",
                    "organization_id",
                )
            )

    return render(
        request,
        "organizations/select_workspace.html",
        {
            "memberships": memberships,
            "active_organization_id": request.session.get("active_organization_id"),
        },
    )


@login_required
@require_POST
def activate_workspace_action(request):
    raw_id = request.POST.get("organization_id")

    try:
        organization_id = UUID(str(raw_id))
    except (
        TypeError,
        ValueError,
        AttributeError,
    ) as error:
        raise PermissionDenied("The selected workspace is invalid.") from error

    subscription = _subscription_for_user(request.user)

    if (
        subscription is None
        or not subscription.grants_access
        or subscription.organization_id != organization_id
    ):
        request.session.pop(
            "active_organization_id",
            None,
        )
        raise PermissionDenied(
            "Your subscription does not authorize this workspace."
        )

    with identity_transaction(request.user.id):
        membership = (
            OrganizationMember.objects.filter(
                user_id=request.user.id,
                organization_id=organization_id,
            )
            .select_related("organization")
            .first()
        )

    if membership is None:
        request.session.pop(
            "active_organization_id",
            None,
        )
        raise PermissionDenied("You do not have access to this workspace.")

    request.session["active_organization_id"] = str(organization_id)

    messages.success(
        request,
        f"Now working in {membership.organization.name}.",
    )

    return redirect("organizations:workspace-selection")


@login_required
@require_http_methods(["GET", "POST"])
def setup_organization_view(request):
    initial = request.session.get(
        _SETUP_DETAILS_KEY,
        {},
    )

    form = OrganizationSetupForm(
        request.POST or None,
        initial=initial,
    )

    if request.method == "POST" and form.is_valid():
        request.session[_SETUP_DETAILS_KEY] = {
            "name": form.cleaned_data["name"],
            "industry": form.cleaned_data["industry"],
        }

        return redirect("organizations:setup-start")

    return render(
        request,
        "organizations/setup.html",
        {
            "step": 1,
            "form": form,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def setup_organization_start_view(request):
    details = request.session.get(_SETUP_DETAILS_KEY)

    if not details:
        return redirect("organizations:setup")

    initial = {}

    start_choice = request.session.get(_SETUP_START_KEY)

    if start_choice:
        initial["start_choice"] = start_choice

    form = OrganizationStartForm(
        request.POST or None,
        initial=initial,
    )

    if request.method == "POST" and form.is_valid():
        request.session[_SETUP_START_KEY] = form.cleaned_data["start_choice"]

        return redirect("organizations:setup-review")

    return render(
        request,
        "organizations/setup.html",
        {
            "step": 2,
            "form": form,
            "organization_name": details["name"],
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def setup_organization_review_view(request):
    details = request.session.get(_SETUP_DETAILS_KEY)
    start_choice = request.session.get(_SETUP_START_KEY)

    if not details:
        return redirect("organizations:setup")

    if not start_choice:
        return redirect("organizations:setup-start")

    industry_label = dict(Organization.Industry.choices).get(
        details["industry"],
        details["industry"],
    )

    if request.method == "POST":
        validation_form = OrganizationSetupForm(details)

        if not validation_form.is_valid():
            request.session.pop(
                _SETUP_DETAILS_KEY,
                None,
            )
            request.session.pop(
                _SETUP_START_KEY,
                None,
            )

            messages.error(
                request,
                "Please review your organization details again.",
            )

            return redirect("organizations:setup")

        organization_id = _create_and_bind_owned_workspace(
            user=request.user,
            name=validation_form.cleaned_data["name"],
            industry=validation_form.cleaned_data["industry"],
        )

        request.session["active_organization_id"] = str(organization_id)

        request.session.pop(
            _SETUP_DETAILS_KEY,
            None,
        )
        request.session.pop(
            _SETUP_START_KEY,
            None,
        )
        request.session.pop(
            "agentledger_new_account",
            None,
        )

        messages.success(
            request,
            f"{validation_form.cleaned_data['name']} is ready.",
        )

        if start_choice == OrganizationStartForm.START_IMPORT:
            return redirect("imports:upload")

        if start_choice == OrganizationStartForm.START_MANUAL:
            return redirect("inventory:list")

        return redirect("organizations:workspace-selection")

    return render(
        request,
        "organizations/setup.html",
        {
            "step": 3,
            "organization_name": details["name"],
            "industry_label": industry_label,
            "start_choice": start_choice,
            "start_label": dict(
                OrganizationStartForm.base_fields["start_choice"].choices
            ).get(start_choice),
        },
    )
