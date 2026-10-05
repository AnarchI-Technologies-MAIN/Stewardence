import pytest
from django.urls import reverse
from apps.jobs.models import BackgroundJob
from apps.jobs.queue import enqueue_job, claim_next_job, fail_job_with_fence

pytestmark = pytest.mark.django_db(transaction=True)


def test_operations_requires_authentication(client):
    assert client.get(reverse("core-operations")).status_code == 302


def test_operations_shows_recorded_holds_without_live_health_claims(client, report_context):
    _, organization, _, _, _ = report_context
    job = enqueue_job(organization_id=organization.id, job_type=BackgroundJob.Type.REPORT_GENERATION,
        payload={"report_id":"fixture-only"}, priority=-100)
    claimed = claim_next_job("operations-test")
    assert claimed.id == job.id
    fail_job_with_fence(job_id=job.id, worker_id="operations-test", claim_token=claimed.claim_token,
        error_code="job_requires_review", safe_summary="SECRET NOT FOR DISPLAY", fingerprint="safe", retryable=False)
    response = client.get(reverse("core-operations"))
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert b"Review is required before it can resume" in response.content
    assert b"SECRET NOT FOR DISPLAY" not in response.content
    assert b"do not establish live service health" in response.content
