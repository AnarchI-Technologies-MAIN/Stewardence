from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_core_worker_fails_closed_when_disabled(settings):
    settings.CORE_WORKFLOWS_ENABLED = False
    settings.DATABASES.pop("worker_runtime", None)

    try:
        call_command("run_core_worker", worker_id="qualification-worker")
    except CommandError as error:
        assert "disabled" in str(error)
    else:
        raise AssertionError("disabled Core workflows must not execute")


def test_core_worker_requires_restricted_database_role(settings):
    settings.CORE_WORKFLOWS_ENABLED = True
    settings.DATABASES.pop("worker_runtime", None)

    try:
        call_command("run_core_worker", worker_id="qualification-worker")
    except CommandError as error:
        assert "WORKER_DATABASE_URL" in str(error)
    else:
        raise AssertionError("Core worker must reject the web database fallback")


def test_core_worker_uses_restricted_role_and_bounded_drain(settings, monkeypatch):
    from apps.jobs.management.commands import run_core_worker

    settings.CORE_WORKFLOWS_ENABLED = True
    settings.DATABASES["worker_runtime"] = settings.DATABASES["default"].copy()
    resolver = object()
    build = Mock(return_value=resolver)
    drain = Mock(return_value=2)
    monkeypatch.setattr(run_core_worker, "build_job_handler_resolver", build)
    monkeypatch.setattr(run_core_worker, "drain_queue", drain)

    call_command(
        "run_core_worker",
        worker_id="qualification-worker",
        max_jobs=2,
    )

    build.assert_called_once_with(using="worker_runtime")
    drain.assert_called_once_with(
        "qualification-worker",
        resolver,
        using="worker_runtime",
        max_jobs=2,
    )


def test_core_worker_rejects_unbounded_batch(settings):
    settings.CORE_WORKFLOWS_ENABLED = True
    settings.DATABASES["worker_runtime"] = settings.DATABASES["default"].copy()

    try:
        call_command(
            "run_core_worker",
            worker_id="qualification-worker",
            max_jobs=26,
        )
    except CommandError as error:
        assert "1 to 25" in str(error)
    else:
        raise AssertionError("Core worker batch must stay bounded")


@pytest.mark.django_db(transaction=True, databases="__all__")
def test_core_worker_command_delivers_report_through_http_renderer(
    report_context, settings, monkeypatch, tmp_path
):
    import os

    from django.db import connections

    from agentledger.tenancy.context import tenant_transaction
    from apps.jobs import handlers as handlers_module
    from apps.jobs import worker as worker_module
    from apps.jobs.models import BackgroundJob, RecoveryReceipt
    from apps.jobs.receipts import verify_recovery_receipt
    from apps.reports.jobs import ensure_report_generation_job
    from apps.reports.models import ReportArtifact
    from apps.reports.services import create_report
    from apps.reports.storage import LocalPrivateReportStorage, build_pdf_object_key

    renderer_url = os.environ.get("STEWARDENCE_HTTP_RENDER_QUALIFICATION_URL")
    if not renderer_url:
        pytest.skip("separate HTTP renderer is only enabled by isolated qualification")

    user, organization, _, _, snapshot = report_context
    settings.CORE_WORKFLOWS_ENABLED = True
    settings.REPORT_RENDERER_URL = renderer_url
    settings.REPORTS_STORAGE_BACKEND = "local"
    storage = LocalPrivateReportStorage(root=tmp_path)
    monkeypatch.setattr(
        handlers_module,
        "build_private_report_storage",
        lambda: storage,
    )
    settings.DATABASES["worker_runtime"] = connections.databases[
        "worker_runtime"
    ].copy()
    report = create_report(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        created_by_id=user.id,
    )
    queued = ensure_report_generation_job(report=report)
    BackgroundJob.objects.filter(pk=queued.id).update(priority=-100)
    failure_types = []
    record_failure = worker_module._record_failure

    def observe_failure(job, execution, error, retryable, using):
        failure_types.append(type(error).__name__)
        return record_failure(job, execution, error, retryable, using)

    monkeypatch.setattr(worker_module, "_record_failure", observe_failure)

    call_command(
        "run_core_worker",
        worker_id="isolated-core-worker",
        max_jobs=1,
    )

    with tenant_transaction(organization.id, using="worker_runtime"):
        completed = BackgroundJob.objects.using("worker_runtime").get(pk=queued.id)
        receipts = list(
            RecoveryReceipt.objects.using("worker_runtime").filter(job=completed)
        )
    assert completed.status == BackgroundJob.Status.COMPLETED, (
        completed.status,
        completed.error_code,
        failure_types,
    )
    assert len(receipts) == 1 and verify_recovery_receipt(receipts[0])
    with tenant_transaction(organization.id, using="owner_runtime"):
        artifact = ReportArtifact.objects.using("owner_runtime").get(
            report_id=report.id
        )

    assert completed.attempts == 1
    assert artifact.content_type == "application/pdf"
    key = build_pdf_object_key(
        organization_id=organization.id,
        assessment_snapshot_id=snapshot.id,
        report_id=report.id,
    )
    stored_pdf = storage.get(key=key)
    assert stored_pdf.startswith(b"%PDF-") and len(stored_pdf) == artifact.size_bytes
