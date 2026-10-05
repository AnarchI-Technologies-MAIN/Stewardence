"""Actual-role owner comparison reads issue no new work or decisions."""

import pytest
from django.urls import reverse

from apps.assessments.models import AssessmentSnapshot, SnapshotCaptureReceipt
from apps.jobs.core_models import DecisionEvent
from apps.jobs.models import BackgroundJob
from apps.reports.models import Report
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_explicit_inventory import form, issue
from tests.test_standard_checkout_route_durability import actual_app_default

__all__ = ["capture_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def effects():
    return tuple(
        model.objects.count()
        for model in (
            AssessmentSnapshot,
            SnapshotCaptureReceipt,
            DecisionEvent,
            BackgroundJob,
            Report,
        )
    )


@pytest.mark.parametrize("reversed_order", [False, True])
def test_owner_comparison_changes_and_chronology_are_read_only(
    capture_context,
    settings,
    client,
    reversed_order,
):
    owner, org = capture_context
    settings.CORE_REVIEW_WORKSPACE_ENABLED = True
    settings.ALLOWED_HOSTS = ["testserver"]
    first_frame = preview(capture_context)
    first = admit(capture_context, first_frame)
    from uuid import UUID

    issue(
        capture_context,
        form(business_owner="Review owner"),
        item_id=UUID(first_frame["inventory_records"][0]["id"]),
    )
    second = admit(capture_context, preview(capture_context))
    client.force_login(owner)
    session = client.session
    session["active_organization_id"] = str(org.id)
    session.save()
    before = effects()
    earlier, later = (second, first) if reversed_order else (first, second)
    with actual_app_default():
        response = client.get(
            reverse("reviews:comparison"),
            {
                "baseline": str(earlier.id),
                "current": str(later.id),
            },
        )
    assert response.status_code == (400 if reversed_order else 200)
    assert response["Cache-Control"] == "private, no-store"
    if not reversed_order:
        assert response.context["comparison"]["schema"] == "core.snapshot_comparison.v2"
        assert b"Captured declaration changes" in response.content
        assert b"Review owner" in response.content and b"Unknown" in response.content
        assert b"Risk: not assessed" in response.content
    assert effects() == before
