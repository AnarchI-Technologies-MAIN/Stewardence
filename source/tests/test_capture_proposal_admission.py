"""Actual-role proposal issuance; not v4 freeze, delivery or verified truth."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connections, transaction

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.inventory.explicit_declarations import NONE
from apps.jobs.core_models import ActionCardRevision
from apps.reviews.models import (
    CaptureProposalAdmissionReceipt,
    CoreProposalAdmissionGate,
)
from apps.reviews.proposal_admission import issue_capture_proposals
from apps.reviews.proposals_v1 import build_review_proposals
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_explicit_inventory import form, issue

__all__ = ["capture_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def enabled(settings):
    settings.CORE_PROPOSAL_ADMISSION_ENABLED = True
    CoreProposalAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})


def issue_proposals(context, snapshot):
    user, org = context
    return issue_capture_proposals(
        organization_id=org.id,
        actor_id=user.id,
        snapshot_id=snapshot.id,
        using="app_runtime",
    )


def envelope(snapshot):
    return {
        "input_payload": snapshot.input_payload,
        "result_payload": snapshot.result_payload,
        "input_sha256": snapshot.input_sha256,
        "result_sha256": snapshot.result_sha256,
    }


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "approval",
        "accounting_fail",
        "non_accounting",
        "known_no_actions",
        "external_transfer",
    ],
)
def test_sql_issuance_matches_complete_permanent_python_contract(
    capture_context, enabled, case
):
    user, org = capture_context
    if case in {"unknown", "accounting_fail", "external_transfer", "known_no_actions"}:
        org.industry = "accounting_bookkeeping"
        org.save(update_fields=["industry"])
    if case == "non_accounting":
        org.industry = "legal"
        org.save(update_fields=["industry"])
    if case in {
        "approval",
        "accounting_fail",
        "known_no_actions",
        "non_accounting",
        "external_transfer",
    }:
        known_item = issue(
            capture_context,
            form(
                display_name="Explicit proposal specimen",
                business_owner="Responsible owner",
                business_purpose="Review declared workflow",
                human_approval="no",
                autonomy_level="3" if case != "known_no_actions" else "0",
                permissions=["write"] if case != "known_no_actions" else [NONE],
                capabilities={
                    "approval": ["communication"],
                    "accounting_fail": ["financial_transaction", "record_modification"],
                    "non_accounting": ["financial_transaction", "record_modification"],
                    "known_no_actions": [NONE],
                    "external_transfer": ["external_transfer"],
                }[case],
                connected_systems=["banking"],
                data_categories=["payroll", "tax_records"],
            ),
        )
    snapshot = admit(capture_context, preview(capture_context))
    revision = issue_proposals(capture_context, snapshot)
    assert revision.cards == build_review_proposals(
        snapshot_id=snapshot.id, capture_envelope=envelope(snapshot)
    )
    assert issue_proposals(capture_context, snapshot).id == revision.id
    receipt = CaptureProposalAdmissionReceipt.objects.get(revision=revision)
    assert receipt.snapshot_id == snapshot.id
    assert receipt.input_sha256 == snapshot.input_sha256
    assert receipt.result_sha256 == snapshot.result_sha256
    assert receipt.revision_sha256 == revision.sha256
    assert all(
        card["resolution_effect"] == "none" and card["resolution_verified"] is False
        for card in revision.cards
    )
    generic = [
        card for card in revision.cards if card["source"]["class"] != "accounting_fail"
    ]
    assert all("severity" not in card and "risk_score" not in card for card in generic)
    if case == "known_no_actions":
        normalized = next(
            record
            for record in snapshot.input_payload["inventory"]
            if record["id"] == str(known_item.id)
        )
        assert normalized["permissions"] == []
        assert normalized["capabilities"] == []
        assert normalized["provenance"]["permissions"] == "Declared"
        assert normalized["provenance"]["capabilities"] == "Declared"
        assert normalized["human_approval"] is False
        assert normalized["autonomy_level"] == 0
        assert not any(
            card["inventory_item_id"] == str(known_item.id)
            and card["source"]["identity"] == "approval"
            for card in revision.cards
        )
    if case in {"accounting_fail", "external_transfer"}:
        assert (
            snapshot.input_payload["industry_applicability"]["industry"]
            == "accounting_bookkeeping"
        )
        assert (
            snapshot.input_payload["industry_applicability"]["policy_state"]
            == "applicable"
        )
        assert any(
            result["result"] == "FAIL"
            for row in snapshot.result_payload["inventory_results"]
            for result in row["policy_results"]
        )
        assert any(
            card["source"]["class"] == "accounting_fail" for card in revision.cards
        )
    if case == "non_accounting":
        assert not any(
            card["source"]["class"] == "accounting_fail" for card in revision.cards
        )


@pytest.mark.parametrize("gate", ["python", "database", "paid", "profile"])
def test_proposal_admission_fails_closed(capture_context, enabled, settings, gate):
    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    if gate == "python":
        settings.CORE_PROPOSAL_ADMISSION_ENABLED = False
    if gate == "database":
        CoreProposalAdmissionGate.objects.filter(id=1).update(enabled=False)
    if gate == "paid":
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "UPDATE billing_subscription SET status='canceled' "
                "WHERE organization_id=%s",
                [org.id],
            )
    if gate == "profile":
        # Operator-only corruption/recovery fixture in the disposable test DB.
        # TRUNCATE does not relax or disable the immutable profile trigger.
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT current_database()")
            assert cursor.fetchone()[0].startswith("test_")
            cursor.execute("TRUNCATE TABLE organization_workflow_profiles")
    with pytest.raises((DatabaseError, ValidationError)):
        issue_proposals(capture_context, snapshot)
    assert CaptureProposalAdmissionReceipt.objects.count() == 0
    assert ActionCardRevision.objects.count() == 0


@pytest.mark.parametrize("using", ["app_runtime", "worker_runtime"])
def test_raw_proposal_receipt_and_revision_insertion_are_denied(using):
    for table in ["review_capture_proposal_receipts", "core_action_card_revisions"]:
        with pytest.raises(DatabaseError, match="permission denied"):
            with connections[using].cursor() as cursor:
                cursor.execute(f"INSERT INTO {table} DEFAULT VALUES")


def test_worker_cannot_issue_or_read_proposal_receipts(capture_context, enabled):
    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    with pytest.raises(DatabaseError, match="permission denied"):
        with (
            tenant_transaction(org.id, using="worker_runtime"),
            connections["worker_runtime"].cursor() as cursor,
        ):
            cursor.execute(
                "SELECT app_private.issue_core_exposure_proposals(%s,%s,%s,%s)",
                [uuid4(), org.id, user.id, snapshot.id],
            )
    with pytest.raises(DatabaseError, match="permission denied"):
        CaptureProposalAdmissionReceipt.objects.using("worker_runtime").count()


def test_private_recompute_and_uuid_extension_members_are_owner_only():
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT n.nspname FROM pg_extension e "
            "JOIN pg_namespace n ON n.oid=e.extnamespace "
            "WHERE e.extname='uuid-ossp'"
        )
        assert cursor.fetchone() == ("app_private",)
    for using in ["app_runtime", "worker_runtime"]:
        with connections[using].cursor() as cursor:
            for signature in [
                "app_private.recompute_capture_proposals_v1(uuid,uuid)",
                "app_private.capture_policy_results_v1(jsonb)",
                "app_private.uuid_generate_v5(uuid,text)",
            ]:
                cursor.execute(
                    "SELECT has_function_privilege(current_user,%s,'EXECUTE')",
                    [signature],
                )
                assert cursor.fetchone() == (False,)


def test_two_actual_app_connections_issue_one_revision_and_receipt(
    capture_context, enabled
):
    snapshot = admit(capture_context, preview(capture_context))
    barrier = Barrier(2)

    def submit():
        connections["app_runtime"].close()
        try:
            barrier.wait(timeout=15)
            return issue_proposals(capture_context, snapshot).id
        finally:
            connections["app_runtime"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(submit) for _ in range(2)]
        ids = [future.result(timeout=30) for future in futures]
    assert ids[0] == ids[1]
    assert ActionCardRevision.objects.count() == 1
    assert CaptureProposalAdmissionReceipt.objects.count() == 1


def test_wrong_context_denied_before_snapshot_lookup(capture_context, enabled):
    user, org = capture_context
    with pytest.raises(DatabaseError, match="identity context"):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
            connections["app_runtime"].cursor() as cursor,
        ):
            cursor.execute(
                "SELECT app_private.issue_core_exposure_proposals(%s,%s,%s,%s)",
                [uuid4(), uuid4(), user.id, uuid4()],
            )
    assert ActionCardRevision.objects.count() == 0


@pytest.mark.parametrize(
    "blocker", ["actor", "organization", "snapshot", "capture_receipt"]
)
def test_paid_authority_revoked_while_issuer_waits_on_fk_target(
    capture_context, enabled, blocker
):
    from time import monotonic, sleep

    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    table, identity = {
        "actor": ("accounts_user", user.id),
        "organization": ("organizations_organization", org.id),
        "snapshot": ("assessment_snapshots", snapshot.id),
        "capture_receipt": ("assessment_capture_receipts", snapshot.id),
    }[blocker]

    def submit():
        connections["app_runtime"].close()
        try:
            return issue_proposals(capture_context, snapshot)
        finally:
            connections["app_runtime"].close()

    from psycopg import sql

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    sql.SQL("SELECT id FROM {} WHERE id=%s FOR UPDATE").format(
                        sql.Identifier(table)
                    ),
                    [identity],
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
                        "position('app_private.issue_core_exposure_proposals' "
                        "in query)>0 AND wait_event_type='Lock')"
                    )
                    waiting = cursor.fetchone()[0]
                if waiting:
                    break
                sleep(0.025)
            assert waiting, "Actual app proposal issuer did not reach held FK target"
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "UPDATE billing_subscription SET status='canceled' "
                    "WHERE organization_id=%s",
                    [org.id],
                )
        with pytest.raises(DatabaseError, match="after waits"):
            future.result(timeout=30)
    assert ActionCardRevision.objects.count() == 0
    assert CaptureProposalAdmissionReceipt.objects.count() == 0


def test_receipt_owner_read_and_immutable_replay(capture_context, enabled):
    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    issue_proposals(capture_context, snapshot)
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        assert CaptureProposalAdmissionReceipt.objects.using("app_runtime").count() == 1
    from apps.organizations.models import OrganizationMember

    OrganizationMember.objects.filter(organization=org, user=user).update(role="viewer")
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        assert CaptureProposalAdmissionReceipt.objects.using("app_runtime").count() == 0
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
        CaptureProposalAdmissionReceipt.objects.all().update(contract="counterfeit")
