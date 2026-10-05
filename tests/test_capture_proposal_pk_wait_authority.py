"""Actual-role chosen PK wait must not retain pre-wait paid authority."""

import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections, transaction

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.billing.models import Subscription
from apps.jobs.core_models import ActionCardRevision
from apps.organizations.models import Organization, OrganizationMember, WorkflowProfile
from apps.reviews.models import (
    CaptureProposalAdmissionReceipt,
    CoreProposalAdmissionGate,
)
from tests.conftest import grant_core_entitlement
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_explicit_inventory import issue

__all__ = ["capture_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def test_chosen_revision_pk_wait_rechecks_paid_authority_after_foreign_rollback(
    capture_context,
    settings,
    *,
    revoke_authority=True,
    iteration=0,
    diagnostic=False,
):
    """No raw counterfeit row: foreign issuer stages a genuine admitted receipt.

    Caller-selected revision UUIDs are admitted by the public SQL API. Browser
    service UUID4 allocation does not close this actual app-login boundary.
    Revocation is an observed committed status change, never clock tolerance.
    """
    settings.CORE_PROPOSAL_ADMISSION_ENABLED = True
    CoreProposalAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})
    target_user, target_org = capture_context
    target_snapshot = admit(capture_context, preview(capture_context))

    foreign_user = get_user_model().objects.create_user("pk-wait-owner@example.invalid")
    foreign_org = Organization.objects.create(name="Foreign PK admission")
    OrganizationMember.objects.create(
        organization=foreign_org, user=foreign_user, role="owner"
    )
    WorkflowProfile.objects.create(
        organization=foreign_org,
        created_by=foreign_user,
        profile="business.v1",
        settings={"name": "PK wait fixture"},
    )
    grant_core_entitlement(foreign_user, foreign_org)
    foreign_context = foreign_user, foreign_org
    issue(foreign_context)
    foreign_snapshot = admit(foreign_context, preview(foreign_context))

    revision_id = uuid4()
    staged = Event()
    release = Event()
    target_name = "proposal-pk-target-" + uuid4().hex
    foreign_pid = []
    observations = {}
    replay_same_identity = None
    wait_started = None

    def foreign_transaction():
        connections.close_all()
        try:
            with (
                identity_transaction(foreign_user.id, using="app_runtime"),
                tenant_transaction(foreign_org.id, using="app_runtime"),
                connections["app_runtime"].cursor() as cursor,
            ):
                cursor.execute("SELECT pg_backend_pid()")
                foreign_pid.append(cursor.fetchone()[0])
                cursor.execute(
                    "SELECT app_private.issue_core_exposure_proposals(%s,%s,%s,%s)",
                    [revision_id, foreign_org.id, foreign_user.id, foreign_snapshot.id],
                )
                assert cursor.fetchone()[0] == revision_id
                staged.set()
                assert release.wait(timeout=30), "Controlled PK blocker never released"
                transaction.set_rollback(True, using="app_runtime")
        finally:
            connections.close_all()

    def target_transaction():
        connections.close_all()
        try:
            with (
                identity_transaction(target_user.id, using="app_runtime"),
                tenant_transaction(target_org.id, using="app_runtime"),
                connections["app_runtime"].cursor() as cursor,
            ):
                cursor.execute(
                    "SELECT set_config('application_name',%s,false)", [target_name]
                )
                cursor.execute(
                    "SELECT app_private.issue_core_exposure_proposals(%s,%s,%s,%s)",
                    [revision_id, target_org.id, target_user.id, target_snapshot.id],
                )
                return "admitted", cursor.fetchone()[0]
        except DatabaseError as error:
            return "denied", str(error)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        blocker = pool.submit(foreign_transaction)
        target = None
        try:
            assert staged.wait(timeout=15), "Foreign genuine issuer never staged"
            wait_started = monotonic()
            target = pool.submit(target_transaction)
            deadline = monotonic() + 15
            confirmed_wait = False
            while monotonic() < deadline:
                with connections["default"].cursor() as cursor:
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute(
                        "SELECT EXISTS(SELECT 1 FROM pg_stat_activity a WHERE "
                        "a.application_name=%s AND a.usename='agentledger_app' "
                        "AND a.wait_event_type='Lock' "
                        "AND %s=ANY(pg_blocking_pids(a.pid)))",
                        [target_name, foreign_pid[0]],
                    )
                    confirmed_wait = cursor.fetchone()[0]
                if confirmed_wait:
                    break
                if target.done():
                    pytest.fail(
                        f"Target exited before unique-PK wait: {target.result()}"
                    )
                release.wait(timeout=0.025)
            assert confirmed_wait, "Target never waited on foreign admitted revision PK"
            if revoke_authority:
                Subscription.objects.filter(organization=target_org).update(
                    status="canceled"
                )
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "SELECT clock_timestamp(),app_private.core_owner_entitled(%s,%s),"
                    "app_private.core_work_allowed(%s)",
                    [target_org.id, target_user.id, target_org.id],
                )
                clock, entitled, work_allowed = cursor.fetchone()
            observations.update(
                clock=clock.isoformat(),
                entitled=entitled,
                work_allowed=work_allowed,
                foreign_pk_wait=True,
                iteration=iteration,
                authority_revoked=revoke_authority,
                confirmed_wait_elapsed_ms=round((monotonic() - wait_started) * 1000, 3),
            )
            assert entitled is (not revoke_authority)
            assert work_allowed is (not revoke_authority)
        finally:
            release.set()
        blocker.result(timeout=15)
        assert target is not None
        outcome = target.result(timeout=15)
    if revoke_authority:
        assert outcome[0] == "denied", (observations, outcome)
        assert "authority unavailable after waits" in outcome[1]
        assert not ActionCardRevision.objects.filter(snapshot=target_snapshot).exists()
        assert not CaptureProposalAdmissionReceipt.objects.filter(
            snapshot=target_snapshot
        ).exists()
    else:
        assert outcome == ("admitted", revision_id), (observations, outcome)
        with (
            identity_transaction(target_user.id, using="app_runtime"),
            tenant_transaction(target_org.id, using="app_runtime"),
            connections["app_runtime"].cursor() as cursor,
        ):
            cursor.execute(
                "SELECT app_private.issue_core_exposure_proposals(%s,%s,%s,%s)",
                [revision_id, target_org.id, target_user.id, target_snapshot.id],
            )
            replay_same_identity = cursor.fetchone()[0] == revision_id
            assert replay_same_identity
        assert ActionCardRevision.objects.filter(snapshot=target_snapshot).count() == 1
        assert (
            CaptureProposalAdmissionReceipt.objects.filter(
                snapshot=target_snapshot
            ).count()
            == 1
        )
    assert not ActionCardRevision.objects.filter(snapshot=foreign_snapshot).exists()
    assert not CaptureProposalAdmissionReceipt.objects.filter(
        snapshot=foreign_snapshot
    ).exists()
    if diagnostic:
        target_revision_count = ActionCardRevision.objects.filter(
            snapshot=target_snapshot
        ).count()
        target_receipt_count = CaptureProposalAdmissionReceipt.objects.filter(
            snapshot=target_snapshot
        ).count()
        print(
            "SYNTHETIC_PK_WAIT_TRACE "
            + json.dumps(
                {
                    "iteration": iteration,
                    "scenario": "revoke" if revoke_authority else "stable",
                    "actual_app_lock_wait_confirmed": observations["foreign_pk_wait"],
                    "authority_entitled_when_released": observations["entitled"],
                    "work_allowed_when_released": observations["work_allowed"],
                    "confirmed_wait_elapsed_ms": observations[
                        "confirmed_wait_elapsed_ms"
                    ],
                    "target_outcome": outcome[0],
                    "target_revision_count": target_revision_count,
                    "target_receipt_count": target_receipt_count,
                    "same_identity_replay": replay_same_identity,
                },
                sort_keys=True,
            ),
            flush=True,
        )
