from __future__ import annotations

from uuid import UUID

from django.shortcuts import redirect

from agentledger.tenancy.context import identity_transaction
from apps.billing.models import Subscription


class BillingEntitlementMiddleware:
    ALLOWED_PREFIXES = (
        "/accounts/",
        "/admin/",
        "/billing/",
        "/static/",
        "/healthz",
        "/readyz",
    )

    WORKSPACE_SELECTION_PATH = "/workspaces/"
    WORKSPACE_SETUP_PREFIX = "/workspaces/new/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # This sandbox-only module owns independent authorization transactions.
        if request.path.startswith(("/integrations/quickbooks/", "/integrations/microsoft/", "/integrations/xero/")):
            return self.get_response(request)

        user = request.user

        if not user.is_authenticated:
            return self.get_response(request)

        with identity_transaction(user.id):
            return self._authenticated(request, user)

    def _authenticated(self, request, user):
        if request.path.startswith(self.ALLOWED_PREFIXES):
            return self.get_response(request)

        subscription = (
            Subscription.objects.filter(
                billing_customer__user_id=user.id,
            )
            .only(
                "status",
                "cancel_at_period_end",
                "organization_id",
            )
            .first()
        )

        if subscription is None or not subscription.grants_access:
            return redirect("billing:portfolio")

        if request.path.startswith(self.WORKSPACE_SETUP_PREFIX):
            if subscription.organization_id is not None:
                return redirect("organizations:workspace-selection")

            return self.get_response(request)

        if subscription.organization_id is None:
            if request.path == self.WORKSPACE_SELECTION_PATH:
                return self.get_response(request)

            return redirect("organizations:workspace-selection")

        raw_organization_id = request.session.get("active_organization_id")

        if raw_organization_id:
            try:
                active_organization_id = UUID(str(raw_organization_id))
            except (
                TypeError,
                ValueError,
                AttributeError,
            ):
                request.session.pop(
                    "active_organization_id",
                    None,
                )
                return redirect("organizations:workspace-selection")

            if active_organization_id != subscription.organization_id:
                request.session.pop(
                    "active_organization_id",
                    None,
                )
                return redirect("organizations:workspace-selection")

        return self.get_response(request)
