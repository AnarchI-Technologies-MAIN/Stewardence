import pytest
from django.urls import reverse
from apps.jobs.models import BackgroundJob
from apps.jobs.queue import claim_next_job, fail_job_with_fence
from apps.reports.jobs import ensure_report_generation_job
from apps.reports.services import create_report

pytestmark = pytest.mark.django_db(transaction=True)


def test_report_retry_cannot_bypass_review_hold(client, report_context):
    user, organization, _, _, snapshot = report_context
    report = create_report(organization_id=organization.id,
        assessment_snapshot_id=snapshot.id, created_by_id=user.id)
    queued = ensure_report_generation_job(report=report)
    BackgroundJob.objects.filter(id=queued.id).update(priority=-100)
    claimed = claim_next_job("test-recovery")
    assert claimed.id == queued.id
    fail_job_with_fence(job_id=claimed.id, worker_id="test-recovery",
        claim_token=claimed.claim_token, error_code="job_requires_review",
        safe_summary="Requires review", fingerprint="safe", retryable=False)
    existing = ensure_report_generation_job(report=report)
    assert existing.id == queued.id
    assert existing.status == BackgroundJob.Status.FAILED
    assert BackgroundJob.objects.filter(payload={"report_id":str(report.id)}).count() == 1
    response = client.get(reverse("reports:detail", args=(report.id,)))
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert b"stopped safely and requires review" in response.content
    assert b"Download PDF" not in response.content
