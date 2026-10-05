from __future__ import annotations

import uuid

import pytest

from agentledger.tenancy.context import tenant_transaction
from apps.audit.append import append_audit_event
from apps.audit.jobs import (
    AuditBatchSealHandler,
    AuditBatchSealJobError,
)
from apps.audit.models import (
    AuditEvent,
    AuditMerkleBlock,
)
from apps.jobs.handlers import (
    UnsupportedJobHandler,
    build_job_handler_resolver,
)
from apps.jobs.models import BackgroundJob
from apps.jobs.queue import (
    ClaimedJob,
    enqueue_job,
)
from apps.jobs.worker import drain_queue
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db(
    transaction=True,
    databases="__all__",
)


@pytest.fixture
def organization():
    return Organization.objects.create(
        name="Audit Worker Firm",
    )


def claimed_job(
    organization,
    *,
    job_type=BackgroundJob.Type.AUDIT_BATCH_SEAL,
    payload=None,
):
    if payload is None:
        payload = {}

    return ClaimedJob(
        id=uuid.uuid4(),
        organization_id=organization.id,
        job_type=job_type,
        payload=payload,
        attempts=1,
        claim_token=uuid.uuid4(),
    )


def test_resolver_returns_audit_batch_seal_handler():
    resolver = build_job_handler_resolver(
        using="worker_runtime",
    )

    handler = resolver(
        BackgroundJob.Type.AUDIT_BATCH_SEAL,
    )

    assert isinstance(
        handler,
        AuditBatchSealHandler,
    )
    assert handler.using == "worker_runtime"


def test_resolver_rejects_unimplemented_job_types():
    resolver = build_job_handler_resolver()

    with pytest.raises(
        UnsupportedJobHandler,
        match="No job handler is registered",
    ):
        resolver(
            BackgroundJob.Type.CATALOG_REFRESH,
        )


def test_prepare_accepts_only_audit_batch_seal(
    organization,
):
    handler = AuditBatchSealHandler()

    prepared = handler.prepare(claimed_job(organization))

    assert prepared.organization_id == organization.id


def test_prepare_rejects_wrong_job_type(
    organization,
):
    handler = AuditBatchSealHandler()

    with pytest.raises(
        AuditBatchSealJobError,
        match="wrong job type",
    ):
        handler.prepare(
            claimed_job(
                organization,
                job_type=BackgroundJob.Type.REPORT_GENERATION,
            )
        )


def test_prepare_rejects_payload_parameters(
    organization,
):
    handler = AuditBatchSealHandler()

    with pytest.raises(
        AuditBatchSealJobError,
        match="do not accept payload parameters",
    ):
        handler.prepare(
            claimed_job(
                organization,
                payload={
                    "max_events": 7,
                },
            )
        )


def test_execute_external_refreshes_lease_once(
    organization,
):
    handler = AuditBatchSealHandler()
    prepared = handler.prepare(claimed_job(organization))

    heartbeats = []

    result = handler.execute_external(
        prepared,
        lambda: heartbeats.append("heartbeat"),
    )

    assert result == prepared
    assert heartbeats == ["heartbeat"]


def test_persist_rejects_changed_job_identity(
    organization,
):
    handler = AuditBatchSealHandler()
    job = claimed_job(organization)
    prepared = handler.prepare(job)

    changed = type(prepared)(
        job_id=uuid.uuid4(),
        organization_id=prepared.organization_id,
    )

    with pytest.raises(
        AuditBatchSealJobError,
        match="job identity changed",
    ):
        handler.persist(
            job,
            changed,
        )


def test_persist_rejects_changed_tenant_identity(
    organization,
):
    handler = AuditBatchSealHandler()
    job = claimed_job(organization)
    prepared = handler.prepare(job)

    changed = type(prepared)(
        job_id=prepared.job_id,
        organization_id=uuid.uuid4(),
    )

    with pytest.raises(
        AuditBatchSealJobError,
        match="tenant identity changed",
    ):
        handler.persist(
            job,
            changed,
        )


def test_worker_claims_audit_job_and_seals_event(
    organization,
):
    event = append_audit_event(
        organization_id=organization.id,
        event_type="inventory.created",
        entity_type="inventory_item",
        entity_id=uuid.uuid4(),
        data={
            "monthly_cost": "49.00",
        },
        using="app_runtime",
    )

    resolver = build_job_handler_resolver(
        using="worker_runtime",
    )

    processed = drain_queue(
        "audit-worker-1",
        resolver,
        using="worker_runtime",
        max_jobs=1,
    )

    assert processed == 1

    with tenant_transaction(
        organization.id,
        using="app_runtime",
    ):
        event.refresh_from_db(
            using="app_runtime",
        )

        block = AuditMerkleBlock.objects.using("app_runtime").get(
            organization=organization,
        )

    assert event.node_hash is not None
    assert event.batch_block_id is not None
    assert event.batch_position == 0

    assert block.event_count == 1
    assert block.first_event_id == event.id
    assert block.last_event_id == event.id

    job = BackgroundJob.objects.get(
        organization=organization,
        job_type=BackgroundJob.Type.AUDIT_BATCH_SEAL,
    )

    assert job.status == BackgroundJob.Status.COMPLETED
    assert job.attempts == 1


def test_redundant_seal_job_completes_as_safe_noop(
    organization,
):
    event = append_audit_event(
        organization_id=organization.id,
        event_type="inventory.created",
        entity_type="inventory_item",
        data={},
        using="app_runtime",
    )

    with tenant_transaction(
        organization.id,
        using="app_runtime",
    ):
        enqueue_job(
            organization_id=organization.id,
            job_type=BackgroundJob.Type.AUDIT_BATCH_SEAL,
            payload={},
            using="app_runtime",
        )

    resolver = build_job_handler_resolver(
        using="worker_runtime",
    )

    processed = drain_queue(
        "audit-worker-2",
        resolver,
        using="worker_runtime",
        max_jobs=2,
    )

    assert processed == 2

    with tenant_transaction(
        organization.id,
        using="app_runtime",
    ):
        event.refresh_from_db(
            using="app_runtime",
        )

        block_count = (
            AuditMerkleBlock.objects.using("app_runtime")
            .filter(
                organization=organization,
            )
            .count()
        )

    assert event.node_hash is not None
    assert block_count == 1

    assert (
        BackgroundJob.objects.filter(
            organization=organization,
            job_type=BackgroundJob.Type.AUDIT_BATCH_SEAL,
            status=BackgroundJob.Status.COMPLETED,
        ).count()
        == 2
    )


def test_sealer_failure_uses_existing_worker_retry_semantics(
    organization,
    monkeypatch,
):
    append_audit_event(
        organization_id=organization.id,
        event_type="inventory.created",
        entity_type="inventory_item",
        data={},
        using="app_runtime",
    )

    from apps.audit import jobs

    def fail_seal(*args, **kwargs):
        raise RuntimeError("injected audit sealing failure")

    monkeypatch.setattr(
        jobs,
        "seal_tenant_audit_events",
        fail_seal,
    )

    resolver = build_job_handler_resolver(
        using="worker_runtime",
    )

    processed = drain_queue(
        "audit-worker-3",
        resolver,
        using="worker_runtime",
        max_jobs=1,
    )

    assert processed == 1

    job = BackgroundJob.objects.get(
        organization=organization,
        job_type=BackgroundJob.Type.AUDIT_BATCH_SEAL,
    )

    assert job.status == BackgroundJob.Status.QUEUED
    assert job.attempts == 1
    assert job.error_code == "job_execution_failed"
    assert job.safe_error_summary == (
        "The background operation failed and may be retried."
    )
    assert job.error_fingerprint
    assert "injected audit sealing failure" not in (job.safe_error_summary or "")

    event = AuditEvent.objects.get(
        organization=organization,
    )

    assert event.node_hash is None
    assert event.batch_block_id is None
    assert event.batch_position is None
