"""Actual-role closed render projection, independent of renderer validation."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest
from django.db import DatabaseError, connections, transaction

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.jobs.core_models import DecisionEvent
from apps.jobs.handlers import build_job_handler_resolver
from apps.jobs.models import BackgroundJob
from apps.jobs.queue import claim_next_job
from apps.jobs.worker import JobExecution, execute_claimed_job
from apps.reports.artifact_services import read_verified_pdf_artifact
from apps.reports.jobs import ensure_report_generation_job
from apps.reports.services import create_report
from apps.reports.storage import LocalPrivateReportStorage
from apps.reviews.context import build_pack_context
from apps.reviews.models import PackCompletion, ReviewCycle
from apps.reviews.services import freeze_cycle, open_cycle
from tests.test_core_decisions import decide
from tests.test_core_decisions import decision_context as decision_context
from tests.test_review_pack_lifecycle import (
    claimed,
    handler,
    request,
)
from tests.test_review_pack_lifecycle import (
    enabled as enabled,
)
from tests.test_review_pack_lifecycle import (
    pack_context as pack_context,
)

# Imported fixtures are registered in this module for pytest discovery.
__all__ = ["decision_context", "enabled", "pack_context"]

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def projection(job):
    with tenant_transaction(job.organization_id, using="worker_runtime"):
        with connections["worker_runtime"].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.review_pack_projection(%s,%s)",
                [job.id, job.claim_token],
            )
            value = cursor.fetchone()[0]
    return json.loads(value) if isinstance(value, str) else value


def test_worker_projection_prepares_same_snapshot_and_ordered_exposures(
    pack_context, enabled, tmp_path
):
    user, org, snapshot, pack = pack_context
    staged = request(pack_context)
    job = claimed(pack_context)
    value = projection(job)
    assert value["request_id"] == str(staged.id) and value["pack_id"] == str(pack.id)
    assert (
        value["snapshot_input"] == snapshot.input_payload
        and value["snapshot_result"] == snapshot.result_payload
    )
    with tenant_transaction(org.id, using="worker_runtime"):
        prepared = handler(tmp_path).prepare(job)
    context = prepared.report_context
    assert context["context_version"] == "AL-REVIEW-PACK-CONTEXT-1"
    assert context["title"] == "Frozen AI Evidence Review Pack"
    assert context["review_pack"]["manifest"] == pack.manifest
    assert [
        row["source_record"] for row in context["review_pack"]["exposure_reviews"]
    ] == snapshot.input_payload["inventory"]
    assert all(
        row["review"]["verification"] == "not_established"
        for row in context["review_pack"]["exposure_reviews"]
    )
    assert context["review_pack"]["selected_decisions"] == []
    assert (
        context["metadata"]["assessment_date"]
        == pack.manifest["snapshot"]["captured_at"]
    )


def test_projection_renders_frozen_statement_and_proposal_not_later_history(
    decision_context, enabled, tmp_path
):
    user, org, snapshot, revision = decision_context
    first = decide(decision_context)
    cycle = open_cycle(
        organization_id=org.id,
        actor_id=user.id,
        input_snapshot_id=snapshot.id,
        using="app_runtime",
    )
    pack = freeze_cycle(
        cycle_id=cycle.id,
        organization_id=org.id,
        actor_id=user.id,
        expected_revision=1,
        using="app_runtime",
    )
    later = decide(decision_context, expected_previous_event=first, state="defer")
    request((user, org, snapshot, pack))
    job = claimed((user, org, snapshot, pack))
    value = projection(job)
    assert value["selected_decisions"][0]["selection"]["event_id"] == str(first)
    assert value["selected_decisions"][0]["selection"]["event_id"] != str(later)
    assert value["selected_decisions"][0]["proposal"] == revision.cards[0]
    with tenant_transaction(org.id, using="worker_runtime"):
        context = handler(tmp_path).prepare(job).report_context
    statement = context["review_pack"]["selected_decisions"][0]
    assert statement["payload"]["state"] == "act"
    assert statement["payload"]["resolution_verified"] is False


def test_actual_chromium_worker_projection_storage_and_completion_are_one_frozen_pack(
    decision_context, enabled, tmp_path
):
    from io import BytesIO
    from pathlib import Path

    from pypdf import PdfReader

    from renderer.render import render_pdf
    from renderer.schema import validate_report_render_payload
    from renderer.template import render_report_html

    user, org, snapshot, _ = decision_context
    unsafe = "<script>UNSAFE_MARKER</script>"
    first = decide(
        decision_context, notes=unsafe, links=["https://example.invalid/never-fetch"]
    )
    cycle = open_cycle(
        organization_id=org.id,
        actor_id=user.id,
        input_snapshot_id=snapshot.id,
        using="app_runtime",
    )
    pack = freeze_cycle(
        cycle_id=cycle.id,
        organization_id=org.id,
        actor_id=user.id,
        expected_revision=1,
        using="app_runtime",
    )
    later = decide(
        decision_context,
        expected_previous_event=first,
        state="defer",
        notes="LATER_EVENT_SHOULD_NOT_APPEAR",
    )
    staged = request((user, org, snapshot, pack), promote_baseline=True)
    job = claimed((user, org, snapshot, pack))
    captured = []

    class ActualChromium:
        def render(self, context):
            validate_report_render_payload(context)
            html = render_report_html(context)
            assert "<script>" not in html and "&lt;script&gt;UNSAFE_MARKER" in html
            captured.append(deepcopy(context))
            return render_pdf(context, output_directory=tmp_path / "chromium")

    storage = LocalPrivateReportStorage(tmp_path / "objects")
    worker = build_job_handler_resolver(
        using="worker_runtime",
        worker_id="review-qualification",
        report_renderer=ActualChromium(),
        report_storage=storage,
    )(BackgroundJob.Type.REPORT_GENERATION)
    execute_claimed_job(
        JobExecution(job=job, worker_id="review-qualification"),
        worker,
        using="worker_runtime",
    )
    completion = PackCompletion.objects.get(request=staged)
    pdf = read_verified_pdf_artifact(artifact=completion.artifact, storage=storage)
    evidence = Path("/qualification-evidence")
    if evidence.is_dir():
        with (evidence / "review-pack-delivery.pdf").open("xb") as exported:
            exported.write(pdf)
        with (evidence / "review-pack-delivery-context.json").open("x") as exported:
            json.dump(captured[0], exported, indent=2)
    text = "\n".join(page.extract_text() for page in PdfReader(BytesIO(pdf)).pages)
    for exact in (
        "Frozen AI Evidence Review Pack",
        "Exposure review of frozen inputs",
        "core.exposure.declarations.v1",
        str(pack.id),
        pack.sha256,
        str(first),
        "<script>UNSAFE_MARKER</script>",
    ):
        assert exact in text
    assert str(later) not in text and "LATER_EVENT_SHOULD_NOT_APPEAR" not in text
    assert captured[0]["review_pack"]["selected_decisions"][0]["payload"]["id"] == str(
        first
    )
    assert completion.payload["manifest_sha256"] == pack.sha256
    assert ReviewCycle.objects.get(pk=cycle.id).state == "COMPLETED"
    assert BackgroundJob.objects.get(pk=job.id).status == "completed"
    assert list((tmp_path / "chromium").iterdir()) == []


@pytest.mark.parametrize(
    "attack", ["missing", "wrong_proposal", "live_substitution", "verified_label"]
)
def test_actual_frozen_projection_cannot_render_changed_statement(
    decision_context, enabled, tmp_path, attack
):
    from renderer.schema import (
        InvalidReportRenderPayload,
        validate_report_render_payload,
    )

    user, org, snapshot, _ = decision_context
    first = decide(decision_context)
    cycle = open_cycle(
        organization_id=org.id,
        actor_id=user.id,
        input_snapshot_id=snapshot.id,
        using="app_runtime",
    )
    pack = freeze_cycle(
        cycle_id=cycle.id,
        organization_id=org.id,
        actor_id=user.id,
        expected_revision=1,
        using="app_runtime",
    )
    later = decide(decision_context, expected_previous_event=first, state="defer")
    request((user, org, snapshot, pack))
    job = claimed((user, org, snapshot, pack))
    with tenant_transaction(org.id, using="worker_runtime"):
        context = handler(tmp_path).prepare(job).report_context
    validate_report_render_payload(context)
    altered = deepcopy(context)
    entries = altered["review_pack"]["selected_decisions"]
    if attack == "missing":
        altered["review_pack"]["selected_decisions"] = []
    if attack == "wrong_proposal":
        entries[0]["proposal"]["proposal"] = "Changed proposal"
    if attack == "live_substitution":
        actual_later = DecisionEvent.objects.get(pk=later)
        entries[0]["payload"] = actual_later.payload
        entries[0]["event_sha256"] = actual_later.sha256
        entries[0]["selection"].update(
            event_id=str(later), event_sha256=actual_later.sha256, state="defer"
        )
    if attack == "verified_label":
        entries[0]["payload"]["resolution_verified"] = True
    with pytest.raises(InvalidReportRenderPayload):
        validate_report_render_payload(altered)


def test_ordinary_report_prepare_preserves_legacy_context(pack_context, tmp_path):
    user, org, snapshot, _ = pack_context
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        report = create_report(
            organization_id=org.id,
            assessment_snapshot_id=snapshot.id,
            created_by_id=user.id,
            using="app_runtime",
        )
        queued = ensure_report_generation_job(report=report, using="app_runtime")
    BackgroundJob.objects.filter(id=queued.id).update(priority=-100)
    job = claim_next_job("review-qualification", using="worker_runtime")
    assert job.id == queued.id and projection(job) is None
    contexts = []

    class OrdinaryRenderer:
        def render(self, context):
            contexts.append(context)
            return b"%PDF-1.7\nordinary resolver fixture\n%%EOF\n"

    ordinary = build_job_handler_resolver(
        using="worker_runtime",
        report_renderer=OrdinaryRenderer(),
        report_storage=LocalPrivateReportStorage(tmp_path),
    )(BackgroundJob.Type.REPORT_GENERATION)
    with tenant_transaction(org.id, using="worker_runtime"):
        prepared = ordinary.prepare(job)
    assert prepared.report_context["context_version"] == "AL-REPORT-CONTEXT-2"
    assert "review_pack" not in prepared.report_context
    execute_claimed_job(
        JobExecution(job=job, worker_id="review-qualification"),
        ordinary,
        using="worker_runtime",
    )
    assert (
        contexts[0]["context_version"] == "AL-REPORT-CONTEXT-2"
        and "review_pack" not in contexts[0]
    )
    assert BackgroundJob.objects.get(pk=job.id).status == "completed"


def test_app_cannot_execute_worker_projection(pack_context, enabled):
    user, org, _, _ = pack_context
    with pytest.raises(DatabaseError, match="permission denied"):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
        ):
            with connections["app_runtime"].cursor() as cursor:
                cursor.execute(
                    "SELECT app_private.review_pack_projection(%s,%s)",
                    [uuid4(), uuid4()],
                )


def test_operator_gate_forces_rls_without_runtime_access():
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT relrowsecurity,relforcerowsecurity FROM pg_class "
            "WHERE oid='public.review_lifecycle_gate'::regclass"
        )
        assert cursor.fetchone() == (True, True)
    for alias in ("app_runtime", "worker_runtime"):
        with (
            pytest.raises(DatabaseError, match="permission denied"),
            transaction.atomic(using=alias),
        ):
            with connections[alias].cursor() as cursor:
                cursor.execute("SELECT enabled FROM review_lifecycle_gate")


def test_worker_projection_denies_wrong_tenant(pack_context, enabled):
    request(pack_context)
    job = claimed(pack_context)
    with pytest.raises(DatabaseError, match="lease authority"):
        with tenant_transaction(uuid4(), using="worker_runtime"):
            with connections["worker_runtime"].cursor() as cursor:
                cursor.execute(
                    "SELECT app_private.review_pack_projection(%s,%s)",
                    [job.id, job.claim_token],
                )


@pytest.mark.parametrize(
    "change",
    [
        "manifest",
        "input",
        "result",
        "metadata_time",
        "metadata_snapshot",
        "inventory_order",
        "inventory_missing",
    ],
)
def test_python_render_boundary_rejects_changed_admitted_projection(
    pack_context, enabled, tmp_path, change
):
    _, org, _, _ = pack_context
    request(pack_context)
    job = claimed(pack_context)
    value = projection(job)
    with tenant_transaction(org.id, using="worker_runtime"):
        legacy = handler(tmp_path).delegate.prepare(job).report_context
    altered = deepcopy(value)
    context = deepcopy(legacy)
    if change == "manifest":
        altered["manifest"]["selected_decisions"] = [{"forged": True}]
    if change == "input":
        altered["snapshot_input"]["inventory"][0]["display_name"] = "Changed"
    if change == "result":
        altered["snapshot_result"]["roi"]["provenance"] = "claimed"
    if change == "metadata_time":
        context["metadata"]["assessment_date"] = "2000-01-01"
    if change == "metadata_snapshot":
        context["metadata"]["assessment_snapshot_id"] = str(uuid4())
    if change == "inventory_order":
        context["inventory"][0]["id"] = str(uuid4())
    if change == "inventory_missing":
        context["inventory"] = []
    with pytest.raises(ValueError, match="identity|selection"):
        build_pack_context(context, altered)


def test_context_builder_does_not_alias_snapshot_or_manifest(
    pack_context, enabled, tmp_path
):
    _, org, _, _ = pack_context
    request(pack_context)
    job = claimed(pack_context)
    value = projection(job)
    original = deepcopy(value)
    with tenant_transaction(org.id, using="worker_runtime"):
        legacy = handler(tmp_path).delegate.prepare(job).report_context
    context = build_pack_context(legacy, value)
    context["review_pack"]["manifest"]["selected_decisions"].append(
        {"local": "mutation"}
    )
    context["review_pack"]["exposure_reviews"][0]["source_record"]["display_name"] = (
        "local mutation"
    )
    assert value == original and "review_pack" not in legacy
