"""Protected workflow and retained report reads consume distinct authority."""

from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connections
from django.urls import reverse
from django.utils import timezone

from agentledger.tenancy.context import identity_transaction
from apps.billing.entitlements import issue_paid_coverage
from apps.billing.models import PaidCoverage, Subscription
from apps.jobs.contracts import BranchProfile, Operation, WorkflowRequest
from apps.jobs.core_workflows import configure_control, dispatch
from apps.jobs.queue import (
    LostJobLease,
    claim_next_job,
    complete_job_with_fence,
    lock_job_for_persistence,
)
from apps.organizations.models import WorkflowProfile
from apps.reports.services import create_report
from apps.reviews.services import freeze_cycle, open_cycle

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def paid_review(report_context):
    user, organization, *_ = report_context
    WorkflowProfile.objects.create(
        organization=organization,
        created_by=user,
        profile="business.v1",
        settings={"name": "Main"},
    )
    return report_context


def expire_fixture_generation(subscription):
    """Explicitly issue an expired synthetic generation, not alter a receipt."""
    original = PaidCoverage.objects.get(subscription=subscription).admission_payload
    subscription.stripe_subscription_id = "sub_expired_" + uuid4().hex
    subscription.save(update_fields=["stripe_subscription_id", "updated_at"])
    now = int(timezone.now().timestamp())
    return issue_paid_coverage(
        {
            **original,
            "stripe_subscription_id": subscription.stripe_subscription_id,
            "stripe_invoice_id": "in_expired_" + uuid4().hex,
            "stripe_event_id": "evt_expired_" + uuid4().hex,
            "service_start": now - 3600,
            "service_end": now - 60,
            "paid_at": now - 3500,
        }
    )


def test_expired_owner_can_read_frozen_review_history_but_not_admit_work(
    paid_review, client, settings
):
    settings.CORE_REVIEW_WORKSPACE_ENABLED = True
    settings.REVIEW_PACK_LIFECYCLE_ENABLED = True
    user, organization, _, _, snapshot = paid_review
    cycle = open_cycle(
        organization_id=organization.id,
        actor_id=user.id,
        input_snapshot_id=snapshot.id,
        using="app_runtime",
    )
    pack = freeze_cycle(
        cycle_id=cycle.id,
        organization_id=organization.id,
        actor_id=user.id,
        expected_revision=1,
        using="app_runtime",
    )
    expire_fixture_generation(Subscription.objects.get(organization=organization))
    client.force_login(user)
    session = client.session
    session["active_organization_id"] = str(organization.id)
    session.save()
    assert client.get(reverse("reviews:history")).status_code == 200
    assert (
        client.get(
            reverse("reviews:pack-detail", kwargs={"pack_id": pack.id})
        ).status_code
        == 200
    )
    for route, kwargs in (
        ("reviews:snapshot", {"snapshot_id": snapshot.id}),
        ("reviews:comparison", {}),
    ):
        response = client.get(reverse(route, kwargs=kwargs))
        assert response.status_code == 302
        assert response.url == reverse("billing:portfolio")
    response = client.post(
        reverse("reviews:request-artifact", kwargs={"pack_id": pack.id})
    )
    assert response.status_code == 302
    assert response.url == reverse("billing:portfolio")
    from apps.reviews.models import ArtifactRequest

    assert not ArtifactRequest.objects.filter(pack=pack).exists()


def test_issued_coverage_is_required_by_actual_workflow_admission(paid_review):
    user, organization, *_ = paid_review
    subscription = Subscription.objects.get(organization=organization)
    with identity_transaction(user.id, using="app_runtime"):
        with connections["app_runtime"].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.core_owner_entitled(%s,%s)",
                [organization.id, user.id],
            )
            assert cursor.fetchone()[0] is True
    expire_fixture_generation(subscription)
    with identity_transaction(user.id, using="app_runtime"):
        with connections["app_runtime"].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.core_owner_entitled(%s,%s)",
                [organization.id, user.id],
            )
            assert cursor.fetchone()[0] is False
    with pytest.raises(PermissionDenied):
        dispatch(
            WorkflowRequest(
                organization.id,
                Operation.HEALTH,
                (),
                timezone.now(),
                BranchProfile.BUSINESS,
            ),
            actor_id=user.id,
            using="app_runtime",
        )
    control = configure_control(
        organization_id=organization.id,
        actor_id=user.id,
        mode="paused",
        reason="Owner stops expired work",
        using="app_runtime",
    )
    assert control.mode == "paused"


def test_claim_and_persistence_recheck_current_generation(paid_review):
    from django.db import transaction

    user, organization, _, _, snapshot = paid_review
    dispatch(
        WorkflowRequest(
            organization.id,
            Operation.REPORT,
            (snapshot.id,),
            timezone.now(),
            BranchProfile.BUSINESS,
        ),
        actor_id=user.id,
        using="app_runtime",
    )
    # Fixture assessment audit seals may precede the report in the global queue.
    # Finish those admitted internal jobs; exercise the report claim itself.
    for _ in range(10):
        claim = claim_next_job("paid-boundary", using="worker_runtime")
        assert claim is not None
        if claim.job_type == "report_generation":
            break
        assert claim.job_type == "audit_batch_seal"
        complete_job_with_fence(
            job_id=claim.id,
            worker_id="paid-boundary",
            claim_token=claim.claim_token,
            using="worker_runtime",
        )
    assert claim is not None
    assert claim.job_type == "report_generation"
    assert claim.organization_id == organization.id
    expire_fixture_generation(Subscription.objects.get(organization=organization))
    with connections["worker_runtime"].cursor() as cursor:
        cursor.execute("SELECT app_private.core_work_allowed(%s)", [organization.id])
        assert cursor.fetchone()[0] is False
    with pytest.raises(LostJobLease), transaction.atomic(using="worker_runtime"):
        lock_job_for_persistence(
            job_id=claim.id,
            worker_id="paid-boundary",
            claim_token=claim.claim_token,
            using="worker_runtime",
        )


def test_expired_customer_can_read_existing_reports_but_not_generate(
    paid_review, client
):
    user, organization, _, _, snapshot = paid_review
    report = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    expire_fixture_generation(Subscription.objects.get(organization=organization))
    assert client.get(reverse("reports:history")).status_code == 200
    assert client.get(reverse("reports:detail", args=[report.id])).status_code == 200
    response = client.post(reverse("reports:generate", args=[snapshot.id]))
    assert response.status_code == 302
    assert response.url == reverse("billing:portfolio")


def test_expired_read_exception_cannot_select_another_workspace(paid_review, client):
    _, organization, *_ = paid_review
    expire_fixture_generation(Subscription.objects.get(organization=organization))
    session = client.session
    session["active_organization_id"] = str(uuid4())
    session.save()
    assert client.get(reverse("reports:history")).status_code == 302
