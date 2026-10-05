"""Actual-role capture issuance, not rendering or proof of declaration truth."""

import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connections, transaction

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.assessments.capture_admission import (
    issue_deliberate_capture,
    prepare_capture_preview,
)
from apps.assessments.capture_contract import build_capture_payloads
from apps.assessments.models import (
    AssessmentSnapshot,
    CaptureAdmissionGate,
    SnapshotCaptureReceipt,
)
from apps.jobs.core_workflows import configure_control
from apps.organizations.models import OrganizationMember
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_explicit_inventory import form, issue

__all__ = ["explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def capture_context(explicit_context, settings):
    settings.DELIBERATE_CAPTURE_ENABLED = True
    CaptureAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})
    issue(explicit_context)
    return explicit_context


def preview(context):
    user, org = context
    return prepare_capture_preview(
        organization_id=org.id, actor_id=user.id, using="app_runtime"
    )


def admit(context, frame):
    user, org = context
    return issue_deliberate_capture(
        organization_id=org.id,
        actor_id=user.id,
        reviewed_frame=frame,
        using="app_runtime",
    )


def envelope(context, frame):
    from datetime import datetime

    user, org = context
    profile = frame["workflow_profile"]
    return build_capture_payloads(
        organization_id=org.id,
        created_by_id=user.id,
        assessment_id=UUID(frame["capture_id"]),
        assessment_version=1,
        captured_at=datetime.fromisoformat(frame["reviewed_at"].replace("Z", "+00:00")),
        industry=frame["industry"],
        workflow_profile_id=UUID(profile["id"]),
        workflow_profile=profile["profile"],
        workflow_settings=profile["settings"],
        inventory_records=frame["inventory_records"],
    )


def raw_admit(context, frame, value):
    user, org = context
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
        connections["app_runtime"].cursor() as cursor,
    ):
        cursor.execute(
            "SELECT app_private.issue_deliberate_capture(%s,%s,%s::jsonb,%s::jsonb)",
            [org.id, user.id, json.dumps(frame), json.dumps(value)],
        )
        return cursor.fetchone()[0]


def test_preview_read_only_counts_legacy_and_admit_one_exact_receipt(capture_context):
    before = AssessmentSnapshot.objects.count()
    frame = preview(capture_context)
    assert (
        AssessmentSnapshot.objects.count() == before
        and SnapshotCaptureReceipt.objects.count() == 0
    )
    assert frame["legacy_active_count"] >= 1
    assert frame["excluded_active_count"] >= frame["legacy_active_count"]
    value = admit(capture_context, frame)
    assert value.id == UUID(frame["capture_id"]) == value.assessment_id
    assert value.version == 1 and value.input_payload["snapshot_schema_version"] == 2
    assert value.input_payload["benefit_model"] == {"state": "not_supplied"}
    receipt = SnapshotCaptureReceipt.objects.get(snapshot=value)
    assert (
        receipt.reviewed_frame == frame
        and receipt.created_by_id == capture_context[0].id
    )
    assert admit(capture_context, frame).id == value.id
    assert (
        AssessmentSnapshot.objects.count() == before + 1
        and SnapshotCaptureReceipt.objects.count() == 1
    )


def test_committed_replay_does_not_reinterpret_later_inventory(capture_context):
    frame = preview(capture_context)
    original = admit(capture_context, frame)
    issue(
        capture_context,
        form(display_name="Later changed"),
        item_id=UUID(frame["inventory_records"][0]["id"]),
    )
    assert admit(capture_context, frame).id == original.id
    assert original.input_payload["inventory"][0]["display_name"] != "Later changed"


def test_review_to_admit_inventory_mutation_requires_new_preview(capture_context):
    frame = preview(capture_context)
    issue(
        capture_context,
        form(display_name="Changed"),
        item_id=UUID(frame["inventory_records"][0]["id"]),
    )
    with pytest.raises(DatabaseError, match="source changed"):
        admit(capture_context, frame)
    assert SnapshotCaptureReceipt.objects.count() == 0


def test_new_explicit_record_is_not_a_silent_capture_phantom(capture_context):
    frame = preview(capture_context)
    issue(capture_context)
    with pytest.raises(DatabaseError, match="source changed"):
        admit(capture_context, frame)


@pytest.mark.parametrize("change", ["industry", "profile", "counts", "future", "old"])
def test_reviewed_server_pin_changes_are_rejected(capture_context, change):
    from datetime import datetime, timedelta

    frame = preview(capture_context)
    if change == "industry":
        frame["industry"] = "legal"
    elif change == "profile":
        frame["workflow_profile"]["settings"]["name"] = "Forged"
    elif change == "counts":
        frame["legacy_active_count"] += 1
    else:
        delta = timedelta(minutes=1 if change == "future" else -16)
        frame["reviewed_at"] = (
            (
                datetime.fromisoformat(frame["reviewed_at"].replace("Z", "+00:00"))
                + delta
            )
            .isoformat()
            .replace("+00:00", "Z")
        )
    with pytest.raises((DatabaseError, ValidationError)):
        admit(capture_context, frame)
    assert SnapshotCaptureReceipt.objects.count() == 0


@pytest.mark.parametrize(
    "kind", ["python_gate", "operator_gate", "paused", "viewer", "paid_expired"]
)
def test_authority_denies_preview_and_issue(capture_context, settings, kind):
    user, org = capture_context
    frame = preview(capture_context)
    if kind == "python_gate":
        settings.DELIBERATE_CAPTURE_ENABLED = False
    elif kind == "operator_gate":
        CaptureAdmissionGate.objects.filter(id=1).update(enabled=False)
    elif kind == "paused":
        configure_control(
            organization_id=org.id,
            actor_id=user.id,
            mode="paused",
            reason="Capture authority qualification",
            using="app_runtime",
        )
    elif kind == "viewer":
        OrganizationMember.objects.filter(user=user, organization=org).update(
            role="viewer"
        )
    else:
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "UPDATE billing_subscription SET status='canceled' WHERE "
                "organization_id=%s",
                [org.id],
            )
    for action in (
        lambda: preview(capture_context),
        lambda: admit(capture_context, frame),
    ):
        with pytest.raises((DatabaseError, ValidationError)):
            action()
    assert SnapshotCaptureReceipt.objects.count() == 0


@pytest.mark.parametrize(
    "change", ["benefit", "risk", "input_hash", "result_hash", "schema", "membership"]
)
def test_raw_issuer_checks_result_identity_not_just_caller_hash(
    capture_context, change
):
    import hashlib

    import rfc8785

    frame = preview(capture_context)
    value = envelope(capture_context, frame)
    if change == "benefit":
        value["result_payload"]["benefit_model"] = {"state": "computed"}
    elif change == "risk":
        value["result_payload"]["inventory_results"][0]["risk"]["score"] = 0
    elif change == "schema":
        value["input_payload"]["snapshot_schema_version"] = True
    elif change == "membership":
        value["result_payload"]["inventory_results"][0]["inventory_item_id"] = str(
            uuid4()
        )
    if change not in {"input_hash", "result_hash"}:
        for key in ("input", "result"):
            value[key + "_sha256"] = hashlib.sha256(
                rfc8785.dumps(value[key + "_payload"])
            ).hexdigest()
    else:
        value[change.replace("hash", "sha256")] = "0" * 64
    with pytest.raises(DatabaseError):
        raw_admit(capture_context, frame, value)
    assert SnapshotCaptureReceipt.objects.count() == 0


@pytest.mark.parametrize("using", ["app_runtime", "worker_runtime"])
def test_raw_snapshot_two_and_unknown_schema_insert_are_denied(capture_context, using):
    user, org = capture_context
    for schema in (2, 3, True):
        with pytest.raises(DatabaseError, match="narrow issuance"):
            with (
                identity_transaction(user.id, using=using),
                tenant_transaction(org.id, using=using),
                connections[using].cursor() as cursor,
            ):
                cursor.execute(
                    "INSERT INTO assessment_snapshots(id,organization_id,"
                    "assessment_id,version,created_by_id,captured_at,"
                    "input_payload,result_payload,input_sha256,result_sha256,"
                    "created_at) VALUES(%s,%s,%s,1,%s,clock_timestamp(),"
                    "%s::jsonb,%s::jsonb,%s,%s,clock_timestamp())",
                    [
                        uuid4(),
                        org.id,
                        uuid4(),
                        user.id,
                        json.dumps({"snapshot_schema_version": schema}),
                        json.dumps({"snapshot_schema_version": schema}),
                        "0" * 64,
                        "0" * 64,
                    ],
                )


def test_worker_cannot_read_receipt_or_execute_issuer(capture_context):
    for statement in (
        "SELECT * FROM assessment_capture_receipts",
        "SELECT app_private.prepare_capture_preview(NULL,NULL)",
        "SELECT app_private.issue_deliberate_capture(NULL,NULL,NULL,NULL)",
    ):
        with (
            pytest.raises(DatabaseError, match="permission denied"),
            transaction.atomic(using="worker_runtime"),
        ):
            with connections["worker_runtime"].cursor() as cursor:
                cursor.execute(statement)


def test_receipt_raw_app_writes_and_mutation_denied(capture_context):
    frame = preview(capture_context)
    admit(capture_context, frame)
    user, org = capture_context
    for statement in (
        "DELETE FROM assessment_capture_receipts",
        "UPDATE assessment_capture_receipts SET request_sha256='changed'",
        "INSERT INTO assessment_capture_receipts(id) VALUES(NULL)",
    ):
        with pytest.raises(DatabaseError, match="permission denied"):
            with (
                identity_transaction(user.id, using="app_runtime"),
                tenant_transaction(org.id, using="app_runtime"),
                connections["app_runtime"].cursor() as cursor,
            ):
                cursor.execute(statement)
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
        SnapshotCaptureReceipt.objects.all().update(request_sha256="0" * 64)


def test_changed_request_cannot_reuse_committed_capture_identity(capture_context):
    frame = preview(capture_context)
    admit(capture_context, frame)
    changed = deepcopy(frame)
    changed["reviewed_at"] = changed["reviewed_at"].replace("Z", "+00:00")
    with pytest.raises(DatabaseError, match="replay identity changed"):
        admit(capture_context, changed)


def test_two_connections_same_reviewed_request_issue_one_snapshot(capture_context):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    frame = preview(capture_context)
    barrier = Barrier(2)

    def submit():
        connections["app_runtime"].close()
        try:
            barrier.wait(timeout=15)
            return admit(capture_context, frame).id
        finally:
            connections["app_runtime"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        ids = [future.result(timeout=30) for future in futures]
    assert ids == [UUID(frame["capture_id"])] * 2
    assert SnapshotCaptureReceipt.objects.count() == 1


@pytest.mark.parametrize("blocker", ["organization", "actor"])
def test_paid_authority_is_rechecked_after_last_source_row_wait(
    capture_context, blocker
):
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic, sleep

    user, org = capture_context
    frame = preview(capture_context)

    def submit():
        connections["app_runtime"].close()
        try:
            return admit(capture_context, frame)
        finally:
            connections["app_runtime"].close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            with connections["default"].cursor() as cursor:
                if blocker == "organization":
                    cursor.execute(
                        "SELECT id FROM organizations_organization "
                        "WHERE id=%s FOR UPDATE",
                        [org.id],
                    )
                else:
                    cursor.execute(
                        "SELECT id FROM accounts_user WHERE id=%s FOR UPDATE",
                        [user.id],
                    )
            future = executor.submit(submit)
            deadline = monotonic() + 30
            waiting = False
            while monotonic() < deadline:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE "
                        "usename='agentledger_app' AND "
                        "position('app_private.issue_deliberate_capture' in "
                        "query)>0 AND wait_event_type='Lock')"
                    )
                    waiting = cursor.fetchone()[0]
                if waiting:
                    break
                sleep(0.025)
            assert waiting, "Actual app issuer did not reach the held source row"
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "UPDATE billing_subscription SET status='canceled' WHERE "
                    "organization_id=%s",
                    [org.id],
                )
        with pytest.raises(DatabaseError, match="after waits"):
            future.result(timeout=30)
    assert SnapshotCaptureReceipt.objects.count() == 0
    assert not AssessmentSnapshot.objects.filter(id=UUID(frame["capture_id"])).exists()


def test_receipt_reads_are_owner_only_and_same_tenant(capture_context):
    user, org = capture_context
    frame = preview(capture_context)
    admit(capture_context, frame)
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        assert SnapshotCaptureReceipt.objects.using("app_runtime").count() == 1
    OrganizationMember.objects.filter(organization=org, user=user).update(role="viewer")
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        assert SnapshotCaptureReceipt.objects.using("app_runtime").count() == 0
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(uuid4(), using="app_runtime"),
    ):
        assert SnapshotCaptureReceipt.objects.using("app_runtime").count() == 0


@pytest.mark.parametrize("eligible_count", [0, 101])
def test_sql_preview_never_truncates_or_invents_explicit_records(
    explicit_context, settings, eligible_count
):
    settings.DELIBERATE_CAPTURE_ENABLED = True
    CaptureAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})
    for index in range(eligible_count):
        issue(explicit_context, form(display_name=f"Tool {index}"))
    with pytest.raises(DatabaseError, match="one to one hundred"):
        preview(explicit_context)
    assert SnapshotCaptureReceipt.objects.count() == 0


def test_actual_sql_context_cannot_admit_another_actor_or_tenant(capture_context):
    user, org = capture_context
    frame = preview(capture_context)
    value = envelope(capture_context, frame)
    for organization_id, actor_id in [(uuid4(), user.id), (org.id, uuid4())]:
        with pytest.raises(DatabaseError, match="context invalid"):
            with (
                identity_transaction(user.id, using="app_runtime"),
                tenant_transaction(org.id, using="app_runtime"),
                connections["app_runtime"].cursor() as cursor,
            ):
                cursor.execute(
                    "SELECT app_private.issue_deliberate_capture"
                    "(%s,%s,%s::jsonb,%s::jsonb)",
                    [organization_id, actor_id, json.dumps(frame), json.dumps(value)],
                )
    assert SnapshotCaptureReceipt.objects.count() == 0
