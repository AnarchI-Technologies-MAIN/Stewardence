"""Actual-role capture statements; completion never verifies source truth."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import UUID, uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections, transaction

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.billing.models import Subscription
from apps.jobs.core_decisions_v2 import record_capture_decision
from apps.jobs.core_models import DecisionDeskGate, DecisionEvent
from apps.jobs.core_workflows import configure_control
from apps.organizations.models import Organization, OrganizationMember
from apps.reviews.models import CoreProposalAdmissionGate
from apps.reviews.proposal_admission import issue_capture_proposals
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_explicit_inventory import explicit_context as explicit_context

__all__ = ["capture_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def capture_decision_context(capture_context, settings):
    settings.CORE_PROPOSAL_ADMISSION_ENABLED = True
    settings.DECISION_DESK_ENABLED = True
    CoreProposalAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})
    DecisionDeskGate.objects.update_or_create(id=1, defaults={"enabled": True})
    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    revision = issue_capture_proposals(
        organization_id=org.id,
        actor_id=user.id,
        snapshot_id=snapshot.id,
        using="app_runtime",
    )
    return user, org, snapshot, revision


def envelope(context, **changes):
    revision = context[3]
    e = {
        "schema": "stewardence.core_decision.v2",
        "revision_id": str(revision.id),
        "proposal_id": revision.cards[0]["proposal_id"],
        "proposal_sha256": revision.cards[0]["sha256"],
        "card_index": 0,
        "expected_previous_event": None,
        "event_kind": "execution",
        "state": "completion_recorded",
        "responsible_label": "Named owner",
        "due_date": None,
        "notes": "Owner says complete; not verification.",
        "links": ["https://example.invalid/evidence"],
    }
    return {**e, **changes}


def raw(context, e, *, alias="app_runtime", org=None, actor=None, legacy=False):
    user, organization = context[:2]
    with (
        identity_transaction(user.id, using=alias),
        tenant_transaction(organization.id, using=alias),
        connections[alias].cursor() as cursor,
    ):
        name = "issue_core_decision" if legacy else "issue_core_capture_decision"
        cursor.execute(
            f"SELECT app_private.{name}(%s,%s,%s::jsonb)",
            [org or organization.id, actor or user.id, json.dumps(e)],
        )
        return cursor.fetchone()[0]


def decide(context, **changes):
    user, org, _, revision = context
    e = envelope(context, **changes)
    return record_capture_decision(
        organization_id=org.id,
        actor_id=user.id,
        revision_id=revision.id,
        proposal_id=UUID(e["proposal_id"]),
        proposal_sha256=e["proposal_sha256"],
        card_index=e["card_index"],
        event_kind=e["event_kind"],
        state=e["state"],
        responsible_label=e["responsible_label"],
        notes=e["notes"],
        links=e["links"],
        expected_previous_event=UUID(e["expected_previous_event"])
        if e["expected_previous_event"]
        else None,
        using="app_runtime",
    )


@pytest.mark.parametrize("state", ["completion_recorded", "evidence_reviewed"])
def test_exact_proposal_statement_does_not_promote_frozen_unknown(
    capture_decision_context, state
):
    context = capture_decision_context
    before_cards = context[3].cards
    before_result = context[2].result_payload
    event = DecisionEvent.objects.get(id=decide(context, state=state))
    assert event.payload["schema"] == "stewardence.core_decision_event.v2"
    assert event.payload["proposal_id"] == before_cards[0]["proposal_id"]
    assert event.payload["proposal_sha256"] == before_cards[0]["sha256"]
    assert event.payload["original_outcome"] == "UNKNOWN"
    assert event.payload["resolution_effect"] == "none"
    assert event.payload["source_state_immutable"] is True
    assert event.payload["owner_statement_only"] is True
    assert event.payload["resolution_verified"] is False
    # Issuance returns actual app-role objects; their refresh must retain the
    # same owner identity and tenant context rather than bypassing forced RLS.
    with (
        identity_transaction(context[0].id, using="app_runtime"),
        tenant_transaction(context[1].id, using="app_runtime"),
    ):
        context[3].refresh_from_db(using="app_runtime")
        context[2].refresh_from_db(using="app_runtime")
    assert context[3].cards == before_cards
    assert context[2].result_payload == before_result


@pytest.mark.parametrize(
    "field,value",
    [
        ("proposal_id", str(uuid4())),
        ("proposal_sha256", "a" * 64),
        ("card_index", 1),
        ("card_index", True),
        ("proposal_sha256", None),
        ("original_outcome", "PASS"),
        ("resolution_verified", True),
        ("notes", "x" * 4097),
        ("responsible_label", ""),
        ("links", ["https://user:password@example.invalid"]),
        ("links", ["https://example.invalid"] * 11),
        ("links", None),
        ("state", "verified"),
        ("due_date", "tomorrow"),
    ],
)
def test_raw_identity_and_owner_statement_bounds_fail_closed(
    capture_decision_context, field, value
):
    with pytest.raises(DatabaseError):
        raw(
            capture_decision_context,
            envelope(capture_decision_context, **{field: value}),
        )
    assert not DecisionEvent.objects.exists()


def test_old_issuer_and_private_helper_cannot_admit_capture(capture_decision_context):
    context = capture_decision_context
    e = envelope(context)
    e.pop("proposal_id")
    e.pop("proposal_sha256")
    e["schema"] = "stewardence.core_decision.v1"
    with pytest.raises(DatabaseError):
        raw(context, e, legacy=True)
    with (
        identity_transaction(context[0].id, using="app_runtime"),
        tenant_transaction(context[1].id, using="app_runtime"),
        pytest.raises(DatabaseError),
        transaction.atomic(using="app_runtime"),
    ):
        with connections["app_runtime"].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.issue_core_decision_schema1(%s,%s,%s::jsonb)",
                [context[1].id, context[0].id, json.dumps(e)],
            )
    assert not DecisionEvent.objects.exists()


@pytest.mark.parametrize("alias", ["worker_runtime", "billing_admission"])
def test_other_login_roles_have_no_decision_issuer(capture_decision_context, alias):
    with pytest.raises(DatabaseError):
        raw(capture_decision_context, envelope(capture_decision_context), alias=alias)
    assert not DecisionEvent.objects.exists()


def test_context_identity_and_foreign_revision_denied(capture_decision_context):
    context = capture_decision_context
    foreign = Organization.objects.create(name="Foreign decision organization")
    for changes in ({"org": foreign.id}, {"actor": uuid4()}):
        with pytest.raises(DatabaseError):
            raw(context, envelope(context), **changes)
    with pytest.raises(DatabaseError):
        raw(context, envelope(context, revision_id=str(uuid4())))
    assert not DecisionEvent.objects.exists()


@pytest.mark.parametrize("gate", ["python", "decision", "proposal", "pause", "profile"])
def test_current_admission_gates(capture_decision_context, settings, gate):
    context = capture_decision_context
    if gate == "python":
        settings.DECISION_DESK_ENABLED = False
        with pytest.raises(PermissionDenied):
            decide(context)
    else:
        if gate == "decision":
            DecisionDeskGate.objects.filter(id=1).update(enabled=False)
        if gate == "proposal":
            CoreProposalAdmissionGate.objects.filter(id=1).update(enabled=False)
        if gate == "pause":
            configure_control(
                organization_id=context[1].id,
                actor_id=context[0].id,
                mode="paused",
                reason="Owner stop",
                using="app_runtime",
            )
        if gate == "profile":
            # Privileged isolated-fixture corruption only. The immutable
            # profile DELETE guard stays enabled and is not bypassed by app.
            with connections["default"].cursor() as cursor:
                cursor.execute("TRUNCATE organization_workflow_profiles")
        with pytest.raises(DatabaseError):
            raw(context, envelope(context))
    assert not DecisionEvent.objects.exists()


def test_exact_history_cas_and_concurrent_first_statement(capture_decision_context):
    context = capture_decision_context
    barrier = Barrier(2)

    def submit():
        connections.close_all()
        try:
            barrier.wait(timeout=10)
            try:
                return str(decide(context))
            except DatabaseError:
                return "denied"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit(), range(2)))
    assert results.count("denied") == 1
    first = DecisionEvent.objects.get()
    assert first.sequence == 1
    with pytest.raises(DatabaseError):
        decide(context)
    second = DecisionEvent.objects.get(
        id=decide(
            context, expected_previous_event=str(first.id), state="evidence_reviewed"
        )
    )
    assert second.sequence == 2 and second.previous_event_id == first.id


def test_actor_fk_wait_rechecks_owner_after_wait(capture_decision_context):
    context = capture_decision_context
    started = Event()
    identity = {}

    def submit():
        connections.close_all()
        try:
            with connections["app_runtime"].cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                identity["pid"] = cursor.fetchone()[0]
            started.set()
            try:
                decide(context)
                return "admitted"
            except DatabaseError:
                return "denied"
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic(), connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT id FROM accounts_user WHERE id=%s FOR UPDATE", [context[0].id]
            )
            pending = executor.submit(submit)
            assert started.wait(timeout=10)
            deadline = time.monotonic() + 10
            blocked = False
            while time.monotonic() < deadline:
                cursor.execute(
                    "SELECT cardinality(pg_blocking_pids(%s))>0", [identity["pid"]]
                )
                if cursor.fetchone()[0]:
                    blocked = True
                    break
            assert blocked, "Issuer did not wait on actual actor FK row"
            OrganizationMember.objects.filter(
                organization=context[1], user=context[0]
            ).update(role="viewer")
        # The real revocation commits before awaiting the blocked issuer.
        assert pending.result(timeout=15) == "denied"
    assert not DecisionEvent.objects.exists()


def test_same_tenant_viewer_cannot_issue_or_read_owner_statement(
    capture_decision_context,
):
    context = capture_decision_context
    event_id = decide(context)
    viewer = get_user_model().objects.create_user("capture-viewer@example.invalid")
    OrganizationMember.objects.create(
        organization=context[1], user=viewer, role="viewer"
    )
    viewer_context = (viewer, *context[1:])
    with pytest.raises(DatabaseError):
        raw(viewer_context, envelope(context))
    with (
        identity_transaction(viewer.id, using="app_runtime"),
        tenant_transaction(context[1].id, using="app_runtime"),
    ):
        assert (
            not DecisionEvent.objects.using("app_runtime").filter(id=event_id).exists()
        )
    assert DecisionEvent.objects.count() == 1


def test_app_has_no_raw_statement_write_authority(capture_decision_context):
    context = capture_decision_context
    event_id = decide(context)
    with (
        identity_transaction(context[0].id, using="app_runtime"),
        tenant_transaction(context[1].id, using="app_runtime"),
    ):
        for mutation in (
            "UPDATE core_decision_events SET notes='forged' WHERE id=%s",
            "DELETE FROM core_decision_events WHERE id=%s",
            "INSERT INTO core_decision_events SELECT * "
            "FROM core_decision_events WHERE id=%s",
        ):
            with pytest.raises(DatabaseError), transaction.atomic(using="app_runtime"):
                with connections["app_runtime"].cursor() as cursor:
                    cursor.execute(mutation, [event_id])
    assert DecisionEvent.objects.get(id=event_id).notes != "forged"


@pytest.mark.parametrize("status,allowed", [("past_due", True), ("canceled", False)])
def test_current_issued_coverage_uses_central_paid_policy(
    capture_decision_context, status, allowed
):
    context = capture_decision_context
    Subscription.objects.filter(organization=context[1]).update(status=status)
    if allowed:
        assert DecisionEvent.objects.get(id=decide(context)).sequence == 1
    if not allowed:
        with pytest.raises(DatabaseError):
            decide(context)
        assert not DecisionEvent.objects.exists()


def test_missing_issuance_receipt_cannot_be_replaced_by_self_consistent_cards(
    capture_decision_context,
):
    context = capture_decision_context
    # Privileged disposable-fixture corruption, not an admitted app mutation.
    # The revision and its correct digest survive; issuance authority does not.
    with connections["default"].cursor() as cursor:
        cursor.execute("TRUNCATE review_capture_proposal_receipts")
    with pytest.raises(DatabaseError):
        decide(context)
    assert not DecisionEvent.objects.exists()
