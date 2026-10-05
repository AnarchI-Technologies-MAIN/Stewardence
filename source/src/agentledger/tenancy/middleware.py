from __future__ import annotations

import logging
from uuid import UUID

from django.core.exceptions import PermissionDenied

from apps.organizations.models import OrganizationMember

from .context import activate_tenant, identity_transaction

logger = logging.getLogger(__name__)


class TenantContextResolutionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # This sandbox-only module owns independent authorization transactions.
        if request.path.startswith(
            (
                "/integrations/quickbooks/",
                "/integrations/microsoft/",
                "/integrations/xero/",
            )
        ):
            return self.get_response(request)

        if request.path in {"/healthz", "/readyz"}:
            return self.get_response(request)

        user = request.user
        if not user.is_authenticated:
            return self.get_response(request)

        # Checkout is owner-bound billing work, not tenant work. Do not wrap
        # remote creation in a transaction that can roll back its request key.
        if request.method == "POST" and request.path_info == "/billing/checkout/core/":
            return self.get_response(request)

        with identity_transaction(user.id):
            raw_organization_id = request.session.get("active_organization_id")
            if not raw_organization_id:
                return self.get_response(request)

            try:
                organization_id = UUID(str(raw_organization_id))
            except (TypeError, ValueError, AttributeError) as error:
                request.session.pop("active_organization_id", None)
                raise PermissionDenied("The selected workspace is invalid.") from error

            authorized = OrganizationMember.objects.filter(
                user_id=user.id,
                organization_id=organization_id,
            ).exists()
            if not authorized:
                request.session.pop("active_organization_id", None)
                logger.warning(
                    "Workspace access denied",
                    extra={
                        "user_id": str(user.id),
                        "organization_id": str(organization_id),
                    },
                )
                raise PermissionDenied("You do not have access to this workspace.")

            activate_tenant(organization_id)
            request.organization_id = organization_id
            return self.get_response(request)
