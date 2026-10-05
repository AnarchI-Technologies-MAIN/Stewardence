"""Navigation visibility is convenience; views enforce their own admission."""

from django.conf import settings

from apps.organizations.models import OrganizationMember


def review_navigation(request):
    enabled = getattr(settings, "CORE_REVIEW_WORKSPACE_ENABLED", False) is True
    user = getattr(request, "user", None)
    organization_id = getattr(request, "organization_id", None)
    visible = bool(
        enabled
        and user is not None
        and user.is_authenticated
        and organization_id is not None
        and OrganizationMember.objects.filter(
            organization_id=organization_id,
            user_id=user.id,
            role=OrganizationMember.Role.OWNER,
        ).exists()
    )
    return {"core_review_navigation_enabled": visible}
