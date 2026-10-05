from __future__ import annotations

from django.core.management import call_command
from django.core.management.base import CommandError


class RecordingListener:
    instances = []

    def __init__(self, *, worker_id, listener_dsn):
        self.worker_id = worker_id
        self.listener_dsn = listener_dsn
        self.drain = None
        self.__class__.instances.append(self)

    def run(self, drain):
        self.drain = drain


def test_run_worker_uses_railway_replica_and_runtime_database(monkeypatch):
    from apps.jobs.management.commands import run_worker

    RecordingListener.instances = []
    resolver = object()

    monkeypatch.setenv("RAILWAY_REPLICA_ID", "replica-123")
    monkeypatch.setenv("DATABASE_URL", "postgresql://worker:secret@db.internal/db")
    monkeypatch.setattr(run_worker, "EventDrivenJobListener", RecordingListener)
    monkeypatch.setattr(
        run_worker,
        "build_job_handler_resolver",
        lambda *, using: resolver,
    )

    call_command("run_worker")

    listener = RecordingListener.instances[0]
    assert listener.worker_id == "replica-123"
    assert listener.listener_dsn == "postgresql://worker:secret@db.internal/db"
    assert listener.drain.keywords == {
        "handler_resolver": resolver,
        "using": "default",
    }


def test_run_worker_accepts_explicit_worker_id(monkeypatch):
    from apps.jobs.management.commands import run_worker

    RecordingListener.instances = []

    monkeypatch.delenv("RAILWAY_REPLICA_ID", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://worker:secret@db.internal/db")
    monkeypatch.setattr(run_worker, "EventDrivenJobListener", RecordingListener)
    monkeypatch.setattr(
        run_worker,
        "build_job_handler_resolver",
        lambda *, using: object(),
    )

    call_command("run_worker", worker_id="local-worker")

    assert RecordingListener.instances[0].worker_id == "local-worker"


def test_run_worker_fails_closed_without_identity(monkeypatch):
    monkeypatch.delenv("RAILWAY_REPLICA_ID", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://worker:secret@db.internal/db")

    try:
        call_command("run_worker")
    except CommandError as error:
        assert "worker identity is required" in str(error)
    else:
        raise AssertionError("run_worker must reject a missing worker identity")


def test_run_worker_fails_closed_without_database_url(monkeypatch):
    monkeypatch.setenv("RAILWAY_REPLICA_ID", "replica-123")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    try:
        call_command("run_worker")
    except CommandError as error:
        assert "DATABASE_URL is required" in str(error)
    else:
        raise AssertionError("run_worker must reject a missing database URL")
