from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4

import pytest
from django.db import close_old_connections
from django.utils import timezone

from apps.jobs.listener import EventDrivenJobListener
from apps.jobs.models import BackgroundJob
from apps.jobs.queue import (
    LostJobLease,
    claim_next_job,
    complete_job_with_fence,
    enqueue_job,
    fail_job_with_fence,
    heartbeat_job_with_fence,
    recover_expired_jobs,
)
from apps.organizations.models import Organization

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def organization():
    return Organization.objects.create(name="Phase 13 Queue Firm")


def enqueue(
    organization,
    *,
    job_type=BackgroundJob.Type.RISK_REASSESSMENT,
    priority=100,
):
    return enqueue_job(
        organization_id=organization.id,
        job_type=job_type,
        payload={"inventory_item_id": str(uuid4())},
        priority=priority,
    )


def test_only_approved_mvp_job_types_exist():
    assert set(BackgroundJob.Type.values) == {
        "risk_reassessment",
        "report_generation",
        "catalog_refresh",
        "audit_batch_seal",
    }

    assert all(
        forbidden not in BackgroundJob.Type.values
        for forbidden in (
            "microsoft_discovery",
            "google_discovery",
            "quickbooks_discovery",
            "xero_discovery",
        )
    )


def test_enqueue_rejects_unapproved_job_type_and_non_object_payload(organization):
    with pytest.raises(ValueError, match="Unsupported"):
        enqueue_job(
            organization_id=organization.id,
            job_type="microsoft_discovery",
            payload={},
        )

    with pytest.raises(ValueError, match="JSON object"):
        enqueue_job(
            organization_id=organization.id,
            job_type=BackgroundJob.Type.RISK_REASSESSMENT,
            payload=["not", "an", "object"],
        )


def _race_claim(worker_id):
    close_old_connections()
    try:
        return claim_next_job(worker_id)
    finally:
        close_old_connections()


def test_two_workers_racing_one_job_produce_exactly_one_winner(organization):
    job = enqueue(organization)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(_race_claim, "worker-a")
        second = executor.submit(_race_claim, "worker-b")
        results = [first.result(), second.result()]

    winners = [result for result in results if result is not None]
    losers = [result for result in results if result is None]

    assert len(winners) == 1
    assert len(losers) == 1
    assert winners[0].id == job.id
    assert winners[0].attempts == 1

    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.RUNNING
    assert job.attempts == 1
    assert job.claim_token == winners[0].claim_token


def test_heartbeat_extends_only_the_current_live_claim(organization):
    job = enqueue(organization)
    claim = claim_next_job("worker-a", lease=timedelta(minutes=1))

    assert claim is not None

    job.refresh_from_db()
    original_expiry = job.lock_expires_at

    heartbeat_job_with_fence(
        job_id=job.id,
        worker_id="worker-a",
        claim_token=claim.claim_token,
        lease=timedelta(minutes=5),
    )

    job.refresh_from_db()
    assert job.lock_expires_at > original_expiry

    with pytest.raises(LostJobLease):
        heartbeat_job_with_fence(
            job_id=job.id,
            worker_id="worker-a",
            claim_token=uuid4(),
        )


def test_expired_lease_is_reclaimed_with_new_fencing_token(organization):
    job = enqueue(organization)
    first = claim_next_job("worker-a")

    assert first is not None

    BackgroundJob.objects.filter(pk=job.id).update(
        lock_expires_at=timezone.now() - timedelta(seconds=1)
    )

    assert recover_expired_jobs() == 1

    second = claim_next_job("worker-b")

    assert second is not None
    assert second.id == first.id
    assert second.attempts == 2
    assert second.claim_token != first.claim_token

    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.RUNNING
    assert job.locked_by == "worker-b"
    assert job.claim_token == second.claim_token


def test_stale_worker_completion_and_failure_are_rejected_after_reclaim(
    organization,
):
    job = enqueue(organization)
    first = claim_next_job("worker-a")

    assert first is not None

    BackgroundJob.objects.filter(pk=job.id).update(
        lock_expires_at=timezone.now() - timedelta(seconds=1)
    )
    assert recover_expired_jobs() == 1

    second = claim_next_job("worker-b")
    assert second is not None

    with pytest.raises(LostJobLease):
        complete_job_with_fence(
            job_id=job.id,
            worker_id="worker-a",
            claim_token=first.claim_token,
        )

    with pytest.raises(LostJobLease):
        fail_job_with_fence(
            job_id=job.id,
            worker_id="worker-a",
            claim_token=first.claim_token,
            error_code="stale_worker",
            safe_summary="A stale worker attempted to fail the job.",
            fingerprint="stale-worker-test",
        )

    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.RUNNING
    assert job.locked_by == "worker-b"
    assert job.claim_token == second.claim_token


def test_current_worker_can_complete_live_claim(organization):
    job = enqueue(organization)
    claim = claim_next_job("worker-a")

    assert claim is not None

    complete_job_with_fence(
        job_id=job.id,
        worker_id="worker-a",
        claim_token=claim.claim_token,
    )

    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.COMPLETED
    assert job.completed_at is not None
    assert job.locked_at is None
    assert job.lock_expires_at is None
    assert job.locked_by is None
    assert job.claim_token is None


def test_retry_schedule_uses_database_attempt_count(organization):
    job = enqueue(organization)

    first = claim_next_job("worker-a")
    assert first is not None
    assert first.attempts == 1

    before_first_failure = timezone.now()

    fail_job_with_fence(
        job_id=job.id,
        worker_id="worker-a",
        claim_token=first.claim_token,
        error_code="temporary_failure",
        safe_summary="The temporary operation failed.",
        fingerprint="temporary-failure-1",
    )

    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.QUEUED
    assert job.attempts == 1
    assert job.available_at >= before_first_failure + timedelta(seconds=55)
    assert job.available_at <= timezone.now() + timedelta(seconds=65)

    BackgroundJob.objects.filter(pk=job.id).update(
        available_at=timezone.now() - timedelta(seconds=5)
    )

    second = claim_next_job("worker-b")
    assert second is not None
    assert second.attempts == 2

    before_second_failure = timezone.now()

    fail_job_with_fence(
        job_id=job.id,
        worker_id="worker-b",
        claim_token=second.claim_token,
        error_code="temporary_failure",
        safe_summary="The temporary operation failed again.",
        fingerprint="temporary-failure-2",
    )

    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.QUEUED
    assert job.attempts == 2
    assert job.available_at >= before_second_failure + timedelta(minutes=4, seconds=55)
    assert job.available_at <= timezone.now() + timedelta(minutes=5, seconds=5)


def test_fifth_failure_is_terminal(organization):
    job = enqueue(organization)

    for attempt in range(1, 6):
        BackgroundJob.objects.filter(pk=job.id).update(
            available_at=timezone.now() - timedelta(seconds=5)
        )
        claim = claim_next_job(f"worker-{attempt}")

        assert claim is not None
        assert claim.attempts == attempt

        fail_job_with_fence(
            job_id=job.id,
            worker_id=f"worker-{attempt}",
            claim_token=claim.claim_token,
            error_code="repeat_failure",
            safe_summary="The operation continued to fail.",
            fingerprint="repeat-failure",
        )

    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.FAILED
    assert job.attempts == 5
    assert job.completed_at is not None
    assert job.claim_token is None


class FakeListenerConnection:
    def __init__(self, notifications):
        self.notifications = list(notifications)
        self.listen_statements = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement):
        self.listen_statements.append(str(statement))

    def notifies(self, *, timeout, stop_after):
        del timeout
        del stop_after
        notifications = self.notifications
        self.notifications = []
        return iter(notifications)


def test_listener_drains_immediately_after_listen_before_waiting():
    connection = FakeListenerConnection([])
    drains = []

    listener = EventDrivenJobListener(
        worker_id="worker-a",
        listener_dsn="postgresql://unused",
        recovery_interval_seconds=1,
        connection_factory=lambda *args, **kwargs: connection,
    )

    listener.run_connected_cycle(
        lambda worker_id: drains.append(worker_id),
        max_wakeups=0,
    )

    assert drains == ["worker-a"]
    assert len(connection.listen_statements) == 1
    assert "LISTEN" in connection.listen_statements[0]


def test_listener_recovers_from_missed_notification_by_periodic_scan():
    connection = FakeListenerConnection([])
    drains = []

    listener = EventDrivenJobListener(
        worker_id="worker-a",
        listener_dsn="postgresql://unused",
        recovery_interval_seconds=1,
        connection_factory=lambda *args, **kwargs: connection,
    )

    listener.run_connected_cycle(
        lambda worker_id: drains.append(worker_id),
        max_wakeups=2,
    )

    assert drains == ["worker-a", "worker-a", "worker-a"]


class RecordingHandler:
    def __init__(self):
        self.prepare_contexts = []
        self.external_atomic_states = []
        self.persist_contexts = []
        self.persisted_results = []

    @staticmethod
    def _tenant_context():
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_setting('app.current_organization_id', true)"
            )
            return cursor.fetchone()[0]

    def prepare(self, job):
        self.prepare_contexts.append(self._tenant_context())
        return {"job_id": str(job.id)}

    def execute_external(self, prepared, heartbeat):
        from django.db import connection

        self.external_atomic_states.append(connection.in_atomic_block)
        heartbeat()
        return {"prepared": prepared}

    def persist(self, job, result):
        self.persist_contexts.append(self._tenant_context())
        self.persisted_results.append(result)


class FailingHandler:
    def __init__(self, secret):
        self.secret = secret

    def prepare(self, job):
        return {"job_id": str(job.id)}

    def execute_external(self, prepared, heartbeat):
        heartbeat()
        raise RuntimeError(self.secret)

    def persist(self, job, result):
        raise AssertionError("persist must not run after external failure")


def test_drain_queue_executes_until_queue_is_empty_with_tenant_boundaries(
    organization,
):
    from apps.jobs.worker import drain_queue

    first = enqueue(organization)
    second = enqueue(
        organization,
        job_type=BackgroundJob.Type.REPORT_GENERATION,
    )

    handlers = {
        BackgroundJob.Type.RISK_REASSESSMENT: RecordingHandler(),
        BackgroundJob.Type.REPORT_GENERATION: RecordingHandler(),
    }

    def resolver(job_type):
        return handlers[job_type]

    processed = drain_queue(
        "worker-a",
        resolver,
    )

    assert processed == 2

    first.refresh_from_db()
    second.refresh_from_db()

    assert first.status == BackgroundJob.Status.COMPLETED
    assert second.status == BackgroundJob.Status.COMPLETED

    for handler in handlers.values():
        assert handler.prepare_contexts == [str(organization.id)]
        assert handler.persist_contexts == [str(organization.id)]
        assert handler.external_atomic_states == [False]
        assert len(handler.persisted_results) == 1


def test_drain_queue_records_safe_retry_without_persisting_exception_text(
    organization,
):
    from apps.jobs.worker import drain_queue

    secret = "SECRET-CUSTOMER-DATABASE-TOKEN"
    job = enqueue(organization)

    def resolver(job_type):
        assert job_type == BackgroundJob.Type.RISK_REASSESSMENT
        return FailingHandler(secret)

    processed = drain_queue(
        "worker-a",
        resolver,
        max_jobs=1,
    )

    assert processed == 1

    job.refresh_from_db()

    assert job.status == BackgroundJob.Status.QUEUED
    assert job.attempts == 1
    assert job.error_code == "job_execution_failed"
    assert job.safe_error_summary == (
        "The background operation failed and may be retried."
    )
    assert len(job.error_fingerprint) == 64

    durable_text = " ".join(
        [
            job.error_code or "",
            job.safe_error_summary or "",
            job.error_fingerprint or "",
        ]
    )

    assert secret not in durable_text


def test_drain_queue_failure_does_not_block_next_available_job(organization):
    from apps.jobs.worker import drain_queue

    failed_job = enqueue(
        organization,
        job_type=BackgroundJob.Type.RISK_REASSESSMENT,
        priority=10,
    )
    successful_job = enqueue(
        organization,
        job_type=BackgroundJob.Type.REPORT_GENERATION,
        priority=20,
    )

    successful_handler = RecordingHandler()

    def resolver(job_type):
        if job_type == BackgroundJob.Type.RISK_REASSESSMENT:
            return FailingHandler("private failure detail")
        return successful_handler

    processed = drain_queue(
        "worker-a",
        resolver,
    )

    assert processed == 2

    failed_job.refresh_from_db()
    successful_job.refresh_from_db()

    assert failed_job.status == BackgroundJob.Status.QUEUED
    assert failed_job.attempts == 1

    assert successful_job.status == BackgroundJob.Status.COMPLETED
    assert successful_job.attempts == 1


def test_database_trigger_delivers_live_postgresql_notification(organization):
    import psycopg
    from django.db import connections

    settings = connections["default"].settings_dict

    with psycopg.connect(
        dbname=settings["NAME"],
        user=settings["USER"],
        password=settings["PASSWORD"],
        host=settings["HOST"],
        port=settings["PORT"],
        autocommit=True,
    ) as listener_connection:
        listener_connection.execute("LISTEN agentledger_job_channel")

        job = enqueue(organization)

        notification = next(
            listener_connection.notifies(
                timeout=2,
                stop_after=1,
            ),
            None,
        )

    assert notification is not None
    assert notification.channel == "agentledger_job_channel"
    assert notification.payload == str(organization.id)

    job.refresh_from_db()
    assert job.status == BackgroundJob.Status.QUEUED


def test_listener_reconnects_after_operational_error(monkeypatch):
    import psycopg

    listener = EventDrivenJobListener(
        worker_id="worker-a",
        listener_dsn="postgresql://unused",
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    attempts = []
    sleeps = []

    class StopAfterReconnect(RuntimeError):
        pass

    def connected_cycle(drain_queue):
        del drain_queue
        attempts.append(len(attempts) + 1)

        if len(attempts) == 1:
            raise psycopg.OperationalError("simulated connection loss")

        raise StopAfterReconnect

    monkeypatch.setattr(
        listener,
        "run_connected_cycle",
        connected_cycle,
    )

    with pytest.raises(StopAfterReconnect):
        listener.run(lambda worker_id: None)

    assert attempts == [1, 2]
    assert sleeps == [5]
