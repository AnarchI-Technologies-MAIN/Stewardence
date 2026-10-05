from __future__ import annotations

import pytest

from apps.jobs.models import BackgroundJob
from apps.jobs.queue import (
    claim_next_job,
    enqueue_job,
)
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db(
    transaction=True,
    databases="__all__",
)


def test_raw_claim_hydrates_json_payload_to_dict():
    organization = Organization.objects.create(
        name="Queue Payload Hydration Firm",
    )

    enqueue_job(
        organization_id=organization.id,
        job_type=BackgroundJob.Type.AUDIT_BATCH_SEAL,
        payload={
            "nested": {
                "value": "49.00",
            },
            "enabled": True,
        },
    )

    job = claim_next_job(
        "payload-hydration-worker",
    )

    assert job is not None
    assert isinstance(job.payload, dict)
    assert job.payload == {
        "nested": {
            "value": "49.00",
        },
        "enabled": True,
    }
