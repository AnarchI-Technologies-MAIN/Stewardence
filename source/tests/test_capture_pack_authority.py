"""Additive capture-pack SQL qualification; synthetic renderer is not PDF proof."""

import json
from uuid import UUID

import pytest
from django.db import DatabaseError, connections, transaction

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.assessments.models import SnapshotCaptureReceipt
from apps.jobs.worker import JobExecution, execute_claimed_job
from apps.reviews.models import (
    ArtifactRequest,
    BaselineHead,
    PackCompletion,
    ReviewCycle,
    ReviewLifecycleGate,
)
from apps.reviews.services import freeze_cycle, open_cycle, request_pack_artifact
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_review_pack_lifecycle import claimed, handler

__all__ = ["capture_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def capture_pack(capture_context):
    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
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
    return user, org, snapshot, pack


@pytest.fixture
def lifecycle_enabled(settings):
    settings.REVIEW_PACK_LIFECYCLE_ENABLED = True
    ReviewLifecycleGate.objects.update_or_create(id=1, defaults={"enabled": True})


def requested(context, **kwargs):
    user, org, _, pack = context
    return request_pack_artifact(
        pack_id=pack.id,
        organization_id=org.id,
        actor_id=user.id,
        using="app_runtime",
        **kwargs,
    )


def test_frozen_capture_has_exact_issued_receipt_and_no_baseline_or_decisions(
    capture_pack,
):
    user, org, snapshot, pack = capture_pack
    receipt = SnapshotCaptureReceipt.objects.get(snapshot=snapshot)
    manifest = pack.manifest
    assert manifest["schema"] == "stewardence.review_pack.v3"
    assert manifest["capture"] == {
        "receipt_id": str(receipt.id),
        "request_sha256": receipt.request_sha256,
        "contract": "core.capture.declarations.v1",
        "exposure_contract": "core.exposure.declarations.v1",
    }
    assert manifest["snapshot"]["snapshot_schema"] == 2
    assert (
        manifest["selected_decisions"] == []
        and manifest["selection_scope"] == "empty_capture_kernel"
    )
    assert (
        manifest["baseline_pack_id"] is None
        and manifest["baseline_promotion"] == "blocked"
    )
    assert (
        freeze_cycle(
            cycle_id=pack.cycle_id,
            organization_id=org.id,
            actor_id=user.id,
            expected_revision=1,
            using="app_runtime",
        ).id
        == pack.id
    )


def test_capture_projection_and_readback_use_new_context(
    capture_pack, lifecycle_enabled, tmp_path
):
    staged = requested(capture_pack)
    job = claimed(capture_pack)
    wrapped = handler(tmp_path)
    with tenant_transaction(job.organization_id, using="worker_runtime"):
        prepared = wrapped.prepare(job)
    assert prepared.report_context["context_version"] == "AL-REVIEW-PACK-CONTEXT-2"
    execute_claimed_job(
        JobExecution(job=job, worker_id="review-qualification"),
        wrapped,
        using="worker_runtime",
    )
    completion = PackCompletion.objects.get(request=staged)
    assert completion.payload["baseline_outcome"] == "not_requested"
    assert not BaselineHead.objects.filter(organization=capture_pack[1]).exists()
    assert ArtifactRequest.objects.get(id=staged.id).promote_baseline is False


@pytest.mark.parametrize("after_request", [False, True])
def test_capture_request_cannot_authorize_baseline_promotion(
    capture_pack, lifecycle_enabled, after_request
):
    if after_request:
        requested(capture_pack)
    with pytest.raises(DatabaseError, match="meaning unavailable"):
        requested(capture_pack, promote_baseline=True)
    assert ArtifactRequest.objects.count() == int(after_request)


@pytest.mark.parametrize("using", ["app_runtime", "worker_runtime"])
def test_historical_and_capture_internal_helpers_are_owner_only(using):
    signatures = [
        "app_private.review_snapshot_manifest_v1(uuid,uuid)",
        "app_private.freeze_review_cycle_v2(uuid,uuid,uuid,integer)",
        "app_private.request_review_artifact_v2(uuid,uuid,uuid,integer,uuid,uuid,boolean)",
        "app_private.review_pack_projection_v1(uuid,uuid)",
        "app_private.complete_review_pack_v2(uuid,uuid,uuid,text,uuid)",
        "app_private.review_capture_binding(uuid,uuid)",
        "app_private.review_snapshot_manifest_capture(uuid,uuid)",
        "app_private.freeze_capture_review_cycle(uuid,uuid,uuid,integer)",
        "app_private.capture_pack_projection(uuid,uuid)",
    ]
    with connections[using].cursor() as cursor:
        for signature in signatures:
            cursor.execute(
                "SELECT has_function_privilege(current_user,%s,'EXECUTE')", [signature]
            )
            assert cursor.fetchone() == (False,)


def test_worker_projection_receipt_pins_match_actual_capture(
    capture_pack, lifecycle_enabled
):
    requested(capture_pack)
    job = claimed(capture_pack)
    with (
        tenant_transaction(job.organization_id, using="worker_runtime"),
        connections["worker_runtime"].cursor() as cursor,
    ):
        cursor.execute(
            "SELECT app_private.review_pack_projection(%s,%s)",
            [job.id, job.claim_token],
        )
        value = cursor.fetchone()[0]
    projection = json.loads(value) if type(value) is str else value
    assert projection["schema"] == "stewardence.review_worker_projection.v2"
    assert projection["manifest"] == capture_pack[3].manifest
    assert projection["selected_decisions"] == []
    assert UUID(projection["manifest"]["capture"]["receipt_id"]) == capture_pack[2].id


def test_foreign_owner_cannot_dispatch_capture_pack(capture_pack, lifecycle_enabled):
    user, org, _, pack = capture_pack
    with pytest.raises(DatabaseError):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
            connections["app_runtime"].cursor() as cursor,
        ):
            cursor.execute(
                "SELECT app_private.freeze_review_cycle(%s,%s,%s,1)",
                [pack.cycle_id, org.id, UUID(int=2)],
            )


@pytest.mark.parametrize("operation", ["open", "freeze"])
def test_capture_authority_revoked_during_actor_row_wait(capture_context, operation):
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic, sleep

    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    cycle = None
    if operation == "freeze":
        cycle = open_cycle(
            organization_id=org.id,
            actor_id=user.id,
            input_snapshot_id=snapshot.id,
            using="app_runtime",
        )

    def submit():
        connections["app_runtime"].close()
        try:
            if operation == "open":
                return open_cycle(
                    organization_id=org.id,
                    actor_id=user.id,
                    input_snapshot_id=snapshot.id,
                    using="app_runtime",
                )
            return freeze_cycle(
                cycle_id=cycle.id,
                organization_id=org.id,
                actor_id=user.id,
                expected_revision=1,
                using="app_runtime",
            )
        finally:
            connections["app_runtime"].close()

    issuer = f"app_private.{operation}_review_cycle"
    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "SELECT id FROM accounts_user WHERE id=%s FOR UPDATE", [user.id]
                )
            future = executor.submit(submit)
            deadline = monotonic() + 30
            waiting = False
            while monotonic() < deadline:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE "
                        "usename='agentledger_app' AND position(%s in query)>0 "
                        "AND wait_event_type='Lock')",
                        [issuer],
                    )
                    waiting = cursor.fetchone()[0]
                if waiting:
                    break
                sleep(0.025)
            assert waiting, "Actual capture review issuer never reached actor row wait"
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "UPDATE billing_subscription SET status='canceled' "
                    "WHERE organization_id=%s",
                    [org.id],
                )
        with pytest.raises(DatabaseError):
            future.result(timeout=30)
    assert (
        not SnapshotCaptureReceipt.objects.filter(snapshot_id=snapshot.id)
        .exclude(created_by_id=user.id)
        .exists()
    )
    from apps.reviews.models import PackIdentity

    assert PackIdentity.objects.count() == 0
    assert ReviewCycle.objects.count() == (1 if operation == "freeze" else 0)
