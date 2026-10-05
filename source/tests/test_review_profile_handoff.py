"""Missing setup is explained without implicit profile or work admission."""

import pytest
from django.urls import reverse

from apps.jobs.models import BackgroundJob
from apps.organizations.models import WorkflowProfile
from apps.reviews.models import ReviewCycle

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.mark.parametrize(
    "profile,details",
    [
        ("business.v1", {"name": "Firm branches", "jurisdiction": "US-IL"}),
        (
            "development.v1",
            {
                "name": "Release branches",
                "repository_ref": "firm/app",
                "environment": "local",
            },
        ),
    ],
)
def test_owner_can_choose_meaning_and_return_without_implicit_work(
    client, report_context, settings, profile, details
):
    _, org, _, _, _ = report_context
    settings.CORE_REVIEW_WORKSPACE_ENABLED = True
    history = reverse("reviews:history")
    setup = reverse("organizations:workflow-profile")
    jobs_before = BackgroundJob.objects.count()
    cycles_before = ReviewCycle.objects.count()
    assert not WorkflowProfile.objects.filter(organization=org).exists()
    response = client.get(history)
    assert response.status_code == 200
    assert b"Before requesting a new review" in response.content
    assert setup.encode() in response.content
    assert response.headers["Cache-Control"] == "private, no-store"
    assert not WorkflowProfile.objects.filter(organization=org).exists()
    assert client.post(setup, {"profile": profile, **details}).status_code == 302
    recorded = WorkflowProfile.objects.get(organization=org)
    assert recorded.profile == profile
    assert recorded.settings == details
    response = client.get(setup)
    assert response.status_code == 200
    assert b"Open evidence reviews" in response.content
    assert history.encode() in response.content
    response = client.get(history)
    assert response.status_code == 200
    assert b"Before requesting a new review" not in response.content
    assert BackgroundJob.objects.count() == jobs_before
    assert ReviewCycle.objects.count() == cycles_before


def test_recorded_profile_does_not_advertise_closed_review_workspace(
    client, report_context, settings
):
    settings.CORE_REVIEW_WORKSPACE_ENABLED = False
    setup = reverse("organizations:workflow-profile")
    assert (
        client.post(setup, {"profile": "business.v1", "name": "Firm"}).status_code
        == 302
    )
    response = client.get(setup)
    assert response.status_code == 200
    assert b"Open evidence reviews" not in response.content
    assert client.get(reverse("reviews:history")).status_code == 503
