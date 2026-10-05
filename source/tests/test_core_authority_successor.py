"""Actual-role successor probes, including committed revocation after snapshot."""

import hashlib
import json
from uuid import uuid4

import pytest
import rfc8785
from django.db import DatabaseError, connections, transaction
from django.utils import timezone

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.billing.models import Subscription
from apps.jobs.contracts import BranchProfile, Operation, WorkflowRequest
from apps.jobs.core_models import (
    ActionCardRevision,
    CoreControl,
    KnownEntity,
    WorkflowRun,
)
from apps.jobs.core_workflows import configure_control, dispatch, recorded_health
from apps.jobs.models import BackgroundJob, RecoveryReceipt
from apps.jobs.queue import claim_next_job

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture(autouse=True)
def qualification_workflow_identity_diagnostics(request):
    from tests.workflow_identity_diagnostics import WorkflowIdentityDiagnostics
    with connections['app_runtime'].execute_wrapper(WorkflowIdentityDiagnostics(request.node.nodeid)):
        yield


@pytest.fixture
def configured(report_context):
    from apps.organizations.models import WorkflowProfile

    user, org, *_ = report_context
    WorkflowProfile.objects.create(
        organization=org,
        created_by=user,
        profile="business.v1",
        settings={"name": "Main"},
    )
    return report_context


def health_request(user, org):
    request = WorkflowRequest(
        org.id, Operation.HEALTH, (), timezone.now(), BranchProfile.BUSINESS
    )
    payload = {
        "schema": "stewardence.workflow_receipt.v1",
        "request": request.envelope(),
        "authority": "proposal_only",
        "recorded_health": recorded_health(org.id),
    }
    return request, payload


def issue(request, payload, user, *, encoded=None):
    canonical = encoded if encoded is not None else rfc8785.dumps(payload).decode()
    with connections["app_runtime"].cursor() as c:
        c.execute(
            "SELECT app_private.issue_workflow_run(%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
            [
                uuid4(),
                request.organization_id,
                user.id,
                request.operation.value,
                request.input_sha256,
                request.effective_at,
                json.dumps(payload),
                canonical,
                hashlib.sha256(canonical.encode()).hexdigest(),
                None,
            ],
        )
        return c.fetchone()[0]


@pytest.mark.parametrize("encoding", ["prefix", "order", "numeric", "escape"])
def test_workflow_issuer_rejects_parse_equivalent_noncanonical_digest(
    configured, encoding
):
    user, org, *_ = configured
    request, payload = health_request(user, org)
    canonical = rfc8785.dumps(payload).decode()
    if encoding == "prefix":
        encoded = " " + canonical
    elif encoding == "order":
        encoded = json.dumps(payload, separators=(",", ":"))
    elif encoding == "numeric":
        encoded = canonical.replace(
            '"checked_recent_receipts":0', '"checked_recent_receipts":0.0'
        )
    else:
        encoded = canonical.replace('"proposal_only"', '"proposal_\\u006fnly"')
    assert encoded != canonical and json.loads(encoded) == payload
    with pytest.raises(DatabaseError, match="Workflow payload binding invalid"):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
        ):
            issue(request, payload, user, encoded=encoded)
    assert not WorkflowRun.objects.exists()


def test_paused_health_cannot_be_fabricated_as_normal(configured):
    user, org, *_ = configured
    configure_control(
        organization_id=org.id,
        actor_id=user.id,
        mode="paused",
        reason="Health authority probe",
    )
    request, payload = health_request(user, org)
    assert payload["recorded_health"]["owner_mode"] == "paused"
    payload["recorded_health"]["owner_mode"] = "normal"
    with pytest.raises(DatabaseError, match="Health receipt differs"):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
        ):
            issue(request, payload, user)
    assert not WorkflowRun.objects.exists()
    real = dispatch(request, actor_id=user.id, using="app_runtime")
    assert real.payload["recorded_health"]["owner_mode"] == "paused"


@pytest.mark.parametrize(
    "field,value",
    [
        ("receipt_integrity", False),
        ("review_holds", 99),
        ("checked_recent_receipts", 50),
        ("circuit", "blocked"),
    ],
)
def test_health_fields_must_match_database_observation(configured, field, value):
    user, org, *_ = configured
    request, payload = health_request(user, org)
    payload["recorded_health"][field] = value
    with pytest.raises(DatabaseError, match="Health receipt differs"):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
        ):
            issue(request, payload, user)
    assert not WorkflowRun.objects.exists()


def test_workflow_receipt_rejects_unknown_result_fields(configured):
    user, org, *_ = configured
    request, payload = health_request(user, org)
    payload["invented_authority"] = True
    with pytest.raises(DatabaseError, match="Closed workflow result required"):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
        ):
            issue(request, payload, user)


@pytest.mark.parametrize("operation", ["workflow", "cards", "entity", "control"])
@pytest.mark.parametrize("revocation", ["pause", "lapse"])
def test_repeatable_snapshot_cannot_issue_after_committed_revocation(
    configured, operation, revocation
):
    user, org, _, _, snapshot = configured
    request, payload = health_request(user, org)
    with pytest.raises(DatabaseError, match="Core authority requires read committed"):
        # Establish the snapshot first; revocation commits on the independent
        # default connection before T1 invokes the actual-role issuer/trigger.
        with tenant_transaction(
            org.id, using="app_runtime", isolation="repeatable_read"
        ):
            with identity_transaction(user.id, using="app_runtime"):
                with connections["app_runtime"].cursor() as c:
                    c.execute(
                        "SELECT app_private.core_owner_entitled(%s,%s)",
                        [org.id, user.id],
                    )
                    assert c.fetchone()[0] is True
                if revocation == "pause":
                    configure_control(
                        organization_id=org.id,
                        actor_id=user.id,
                        mode="paused",
                        reason="Independent committed stop",
                    )
                else:
                    Subscription.objects.filter(organization=org).update(
                        status="canceled"
                    )
                if operation == "workflow":
                    issue(request, payload, user)
                elif operation == "cards":
                    with connections["app_runtime"].cursor() as c:
                        c.execute(
                            "SELECT app_private.issue_action_cards(%s,%s,%s,%s)",
                            [uuid4(), org.id, user.id, snapshot.id],
                        )
                elif operation == "entity":
                    KnownEntity.objects.using("app_runtime").create(
                        organization=org,
                        created_by=user,
                        category="services",
                        label="Rejected stale declaration",
                        branch_profile="business.v1",
                        as_of=timezone.now(),
                        sha256="f" * 64,
                    )
                else:
                    CoreControl.objects.using("app_runtime").create(
                        organization=org,
                        created_by=user,
                        mode="normal",
                        reason="Rejected stale resume",
                    )
    assert not WorkflowRun.objects.exists() and not ActionCardRevision.objects.exists()
    assert not KnownEntity.objects.exists()
    assert CoreControl.objects.count() == (1 if revocation == "pause" else 0)


@pytest.mark.parametrize("field", ["worker", "lease", "token"])
def test_null_claim_parameters_leave_job_unclaimed(configured, field):
    user, org, *_ = configured
    job = BackgroundJob.objects.create(
        organization=org,
        job_type="report_generation",
        payload={},
        available_at=timezone.now(),
    )
    values = ["null-probe", "1 minute", uuid4()]
    values[["worker", "lease", "token"].index(field)] = None
    with (
        pytest.raises(DatabaseError, match="Invalid claim parameters"),
        transaction.atomic(using="worker_runtime"),
    ):
        with connections["worker_runtime"].cursor() as c:
            c.execute("SELECT * FROM app_private.claim_job(%s,%s::interval,%s)", values)
    job.refresh_from_db()
    assert job.status == "queued" and job.attempts == 0 and job.lock_expires_at is None
    assert not RecoveryReceipt.objects.exists()


@pytest.mark.parametrize("field", ["id", "worker", "token", "action", "lease"])
def test_null_heartbeat_parameters_leave_claim_intact(configured, field):
    user, org, *_ = configured
    job = BackgroundJob.objects.create(
        organization=org,
        job_type="report_generation",
        payload={},
        available_at=timezone.now(),
        priority=-100,
    )
    claimed = claim_next_job("null-probe", using="worker_runtime")
    assert claimed.id == job.id
    job.refresh_from_db()
    original_expiry = job.lock_expires_at
    values = [
        job.id,
        "null-probe",
        claimed.claim_token,
        "heartbeat",
        "1 minute",
        "",
        "",
        "",
        False,
    ]
    values[["id", "worker", "token", "action", "lease"].index(field)] = None
    with pytest.raises(DatabaseError), transaction.atomic(using="worker_runtime"):
        with connections["worker_runtime"].cursor() as c:
            c.execute(
                "SELECT app_private.finish_job(%s,%s,%s,%s,%s::interval,%s,%s,%s,%s)",
                values,
            )
    job.refresh_from_db()
    assert job.status == "running" and job.claim_token == claimed.claim_token
    assert (
        job.lock_expires_at == original_expiry and not RecoveryReceipt.objects.exists()
    )


@pytest.mark.parametrize("operation", ["claim", "finish", "lock", "recover"])
@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_worker_authority_entrypoints_reject_snapshot_isolation(
    configured, operation, isolation
):
    user, org, *_ = configured
    job = BackgroundJob.objects.create(
        organization=org,
        job_type="report_generation",
        payload={},
        available_at=timezone.now(),
        priority=-100,
    )
    claimed = claim_next_job("isolation-probe", using="worker_runtime")
    assert claimed.id == job.id
    with pytest.raises(DatabaseError, match="Core authority requires read committed"):
        with transaction.atomic(using="worker_runtime"):
            with connections["worker_runtime"].cursor() as c:
                c.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
            with connections["worker_runtime"].cursor() as c:
                if operation == "claim":
                    c.execute(
                        "SELECT * FROM app_private.claim_job(%s,%s::interval,%s)",
                        ["isolation-probe", "1 minute", uuid4()],
                    )
                elif operation == "finish":
                    c.execute(
                        "SELECT app_private.finish_job(%s,%s,%s,%s,%s::interval,%s,%s,%s,%s)",
                        [
                            job.id,
                            "isolation-probe",
                            claimed.claim_token,
                            "complete",
                            None,
                            "",
                            "",
                            "",
                            False,
                        ],
                    )
                elif operation == "lock":
                    c.execute(
                        "SELECT app_private.lock_job_persistence(%s,%s,%s)",
                        [job.id, "isolation-probe", claimed.claim_token],
                    )
                else:
                    c.execute("SELECT app_private.recover_jobs()")
    job.refresh_from_db()
    assert job.status == "running" and not RecoveryReceipt.objects.exists()


@pytest.mark.parametrize("outcome", ["completed", "retry", "review"])
def test_database_health_matches_issued_recovery_receipts(configured, outcome):
    user, org, *_ = configured
    job = BackgroundJob.objects.create(
        organization=org,
        job_type="report_generation",
        payload={},
        available_at=timezone.now(),
        priority=-100,
    )
    claimed = claim_next_job("health-probe", using="worker_runtime")
    assert claimed.id == job.id
    action = "complete" if outcome == "completed" else "fail"
    code = "job_execution_failed" if outcome == "retry" else "job_requires_review"
    with connections["worker_runtime"].cursor() as c:
        c.execute(
            "SELECT app_private.finish_job(%s,%s,%s,%s,%s::interval,%s,%s,%s,%s)",
            [
                job.id,
                "health-probe",
                claimed.claim_token,
                action,
                None,
                code,
                "Synthetic qualification failure.",
                "f" * 64,
                outcome == "retry",
            ],
        )
        assert c.fetchone()[0] is True
    assert RecoveryReceipt.objects.get(job=job).outcome == outcome
    request, payload = health_request(user, org)
    assert payload["recorded_health"]["receipt_integrity"] is True
    assert payload["recorded_health"]["checked_recent_receipts"] == 1
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        issued = issue(request, payload, user)
    assert WorkflowRun.objects.get(pk=issued).payload == payload


def test_private_health_observer_is_not_a_runtime_cross_tenant_api(configured):
    user, org, *_ = configured
    with (
        pytest.raises(DatabaseError, match="permission denied"),
        transaction.atomic(using="app_runtime"),
    ):
        with connections["app_runtime"].cursor() as c:
            c.execute("SELECT app_private.recorded_core_health(%s)", [org.id])


@pytest.mark.parametrize(
    "variant", ["quoted", "missing", "null", "boolean", "fraction", "overflow"]
)
def test_reassessment_count_type_cannot_poison_honest_retry(configured, variant):
    user, org, _, _, snapshot = configured
    request = WorkflowRequest(
        org.id,
        Operation.REASSESS,
        (snapshot.id,),
        timezone.now(),
        BranchProfile.BUSINESS,
    )
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        with connections["app_runtime"].cursor() as c:
            c.execute(
                "SELECT app_private.issue_action_cards(%s,%s,%s,%s)",
                [uuid4(), org.id, user.id, snapshot.id],
            )
            revision_id = c.fetchone()[0]
    revision = ActionCardRevision.objects.get(pk=revision_id)
    count = len(revision.cards)
    payload = {
        "schema": "stewardence.workflow_receipt.v1",
        "request": request.envelope(),
        "authority": "proposal_only",
        "revision_id": str(revision.id),
        "proposal_count": count,
        "state": "reassessed",
    }
    if variant == "missing":
        del payload["proposal_count"]
    else:
        payload["proposal_count"] = {
            "quoted": str(count),
            "null": None,
            "boolean": True,
            "fraction": 0.5,
            "overflow": 9007199254740992,
        }[variant]
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
        if variant == "overflow"
        else rfc8785.dumps(payload).decode()
    )
    with pytest.raises(DatabaseError):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
        ):
            issue(request, payload, user, encoded=encoded)
    assert not WorkflowRun.objects.filter(input_sha256=request.input_sha256).exists()
    honest = dispatch(request, actor_id=user.id, using="app_runtime")
    assert (
        honest.payload["proposal_count"] == count
        and type(honest.payload["proposal_count"]) is int
    )


def test_expiry_recovery_rollback_then_retry_has_one_receipt(configured):
    from datetime import timedelta

    from apps.jobs.queue import recover_expired_jobs

    user, org, *_ = configured
    job = BackgroundJob.objects.create(
        organization=org,
        job_type="catalog_refresh",
        payload={},
        available_at=timezone.now(),
        priority=-1000,
    )
    claimed = claim_next_job("rollback-recovery", using="worker_runtime")
    assert claimed.id == job.id
    BackgroundJob.objects.filter(pk=job.id).update(
        lock_expires_at=timezone.now() - timedelta(seconds=1)
    )

    class RollbackProbe(Exception):
        pass

    with (
        pytest.raises(RollbackProbe),
        tenant_transaction(org.id, using="worker_runtime"),
    ):
        assert recover_expired_jobs(using="worker_runtime") == 1
        assert (
            RecoveryReceipt.objects.using("worker_runtime").filter(job=job).count() == 1
        )
        raise RollbackProbe()
    job.refresh_from_db()
    assert (
        job.status == "running" and not RecoveryReceipt.objects.filter(job=job).exists()
    )
    assert recover_expired_jobs(using="worker_runtime") == 1
    assert recover_expired_jobs(using="worker_runtime") == 0
    assert RecoveryReceipt.objects.filter(job=job).count() == 1


def test_overlapping_recovery_sets_keep_global_control_order_with_stale_candidate(
    configured,
):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta

    from conftest import grant_queue_owner
    from django.db import close_old_connections

    from apps.jobs.queue import recover_expired_jobs
    from apps.organizations.models import Organization

    user, org, *_ = configured
    other = Organization.objects.create(name="Second recovery tenant")
    grant_queue_owner(other)
    low, high = sorted([org, other], key=lambda item: item.id)
    jobs = []
    base = timezone.now() - timedelta(seconds=10)
    for index, owner in enumerate([low, high, low]):
        job = BackgroundJob.objects.create(
            organization=owner,
            job_type="catalog_refresh",
            payload={},
            available_at=timezone.now(),
            priority=-3000 + index,
        )
        claimed = claim_next_job("ordered-recovery", using="worker_runtime")
        assert claimed.id == job.id
        BackgroundJob.objects.filter(pk=job.id).update(
            lock_expires_at=base + timedelta(seconds=index)
        )
        jobs.append(job)

    def recover(name):
        close_old_connections()
        try:
            with transaction.atomic(using="worker_runtime"):
                with connections["worker_runtime"].cursor() as c:
                    c.execute("SELECT set_config('application_name',%s,true)", [name])
                    c.execute("SET LOCAL lock_timeout='15s'")
                    c.execute("SET LOCAL statement_timeout='20s'")
                return recover_expired_jobs(using="worker_runtime")
        finally:
            connections["worker_runtime"].close()

    def wait(name):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with connections["default"].cursor() as c:
                c.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE application_name=%s AND wait_event='advisory')",
                    [name],
                )
                if c.fetchone()[0]:
                    return
            time.sleep(0.02)
        pytest.fail("Recovery did not reach its advisory-lock barrier")

    with connections["default"].cursor() as c:
        c.execute(
            "SELECT pg_advisory_lock(hashtextextended(%s,0))",
            ["core:" + str(low.id) + ":control"],
        )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(recover, "recovery-all-candidates")
            wait("recovery-all-candidates")
            BackgroundJob.objects.filter(pk=jobs[0].id).update(
                status="failed",
                completed_at=timezone.now(),
                locked_at=None,
                lock_expires_at=None,
                locked_by=None,
                claim_token=None,
                error_code="lease_expired",
                safe_error_summary="Synthetic expired lease.",
                error_fingerprint="f" * 64,
            )
            second = pool.submit(recover, "recovery-stale-subset")
            wait("recovery-stale-subset")
            with connections["default"].cursor() as c:
                c.execute(
                    "SELECT pg_try_advisory_xact_lock(hashtextextended(%s,0))",
                    ["core:" + str(high.id) + ":control"],
                )
                assert c.fetchone()[0] is True
                c.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s,0))",
                    ["core:" + str(low.id) + ":control"],
                )
            assert first.result(timeout=15) + second.result(timeout=15) == 2
    finally:
        with connections["default"].cursor() as c:
            c.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s,0))",
                ["core:" + str(low.id) + ":control"],
            )
    assert RecoveryReceipt.objects.filter(job_id__in=[j.id for j in jobs]).count() == 3
    assert (
        not BackgroundJob.objects.filter(id__in=[j.id for j in jobs])
        .exclude(status="failed")
        .exists()
    )
