"""Exact-card owner statements using actual isolated PostgreSQL runtime roles."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, connections, transaction

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.assessments.snapshots import canonical_sha256
from apps.jobs.core_decisions import record_decision
from apps.jobs.core_models import ActionCardRevision, DecisionDeskGate, DecisionEvent
from apps.jobs.core_workflows import configure_control
from apps.organizations.models import Organization, WorkflowProfile

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def decision_context(report_context, settings):
    user, org, _, _, snapshot = report_context
    WorkflowProfile.objects.get_or_create(
        organization=org,
        defaults={
            "created_by": user,
            "profile": "business.v1",
            "settings": {"name": "Decision fixture"},
        },
    )
    settings.DECISION_DESK_ENABLED = True
    DecisionDeskGate.objects.update_or_create(id=1, defaults={"enabled": True})
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        with connections["app_runtime"].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.issue_action_cards(%s,%s,%s,%s)",
                [uuid4(), org.id, user.id, snapshot.id],
            )
            revision_id = cursor.fetchone()[0]
    revision = ActionCardRevision.objects.get(pk=revision_id)
    assert revision.cards, "Fixture requires an actually issued proposal"
    return user, org, snapshot, revision


def decide(context, **changes):
    user, org, _, revision = context
    options = dict(
        organization_id=org.id,
        actor_id=user.id,
        revision_id=revision.id,
        card_index=0,
        event_kind="disposition",
        state="act",
        responsible_label="Named owner",
        notes="Owner decision rationale",
        links=["https://example.invalid/evidence"],
        using="app_runtime",
    )
    options.update(changes)
    return record_decision(**options)


def envelope(context, **changes):
    e = {
        "schema": "stewardence.core_decision.v1",
        "revision_id": str(context[3].id),
        "card_index": 0,
        "expected_previous_event": None,
        "event_kind": "disposition",
        "state": "act",
        "responsible_label": "Named owner",
        "due_date": None,
        "notes": "Owner rationale",
        "links": [],
    }
    e.update(changes)
    return e


def raw_issue(context, e, alias="app_runtime"):
    with (
        identity_transaction(context[0].id, using=alias),
        tenant_transaction(context[1].id, using=alias),
    ):
        with connections[alias].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.issue_core_decision(%s,%s,%s::jsonb)",
                [context[1].id, context[0].id, json.dumps(e)],
            )
            return cursor.fetchone()[0]


def selected(context, snapshot=None, org=None):
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT app_private.selected_core_decisions(%s,%s)",
            [snapshot or context[2].id, org or context[1].id],
        )
        value = cursor.fetchone()[0]
        return json.loads(value) if isinstance(value, str) else value


def test_exact_binding_append_only_statement_and_selection(decision_context):
    first = decide(decision_context, due_date=date(2026, 12, 1))
    row = DecisionEvent.objects.get(pk=first)
    revision = decision_context[3]
    assert row.card_sha256 == canonical_sha256(revision.cards[0])
    assert row.revision_sha256 == revision.sha256
    assert row.snapshot_result_sha256 == decision_context[2].result_sha256
    assert row.sha256 == canonical_sha256(row.payload)
    assert row.payload["owner_statement_only"] is True
    assert row.payload["resolution_verified"] is False
    second = decide(
        decision_context,
        expected_previous_event=first,
        event_kind="execution",
        state="completion_recorded",
    )
    assert DecisionEvent.objects.get(pk=second).previous_event_id == first
    assert selected(decision_context)[0]["event_id"] == str(second)
    assert selected(decision_context)[0]["resolution_verified"] is False
    assert DecisionEvent.objects.get(pk=second).sequence == 2
    with pytest.raises(DatabaseError), transaction.atomic():
        DecisionEvent.objects.filter(pk=first).update(state="verified")
    with pytest.raises(DatabaseError), transaction.atomic():
        with connections["default"].cursor() as cursor:
            cursor.execute("DELETE FROM core_decision_events WHERE id=%s", [second])


def test_feature_and_operator_gates_fail_closed(decision_context, settings):
    settings.DECISION_DESK_ENABLED = False
    with pytest.raises(PermissionDenied):
        decide(decision_context)
    settings.DECISION_DESK_ENABLED = True
    DecisionDeskGate.objects.filter(pk=1).update(enabled=False)
    with pytest.raises(DatabaseError):
        decide(decision_context)
    assert selected(decision_context) == []
    assert not DecisionEvent.objects.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"card_index": None},
        {"card_index": True},
        {"card_index": -1},
        {"card_index": 999999},
        {"responsible_label": None},
        {"responsible_label": ""},
        {"responsible_label": "x" * 201},
        {"notes": None},
        {"notes": "x" * 4097},
        {"links": None},
        {"links": ["https://example.invalid"] * 11},
        {"links": ["http://example.invalid"]},
        {"links": ["https://user:password@example.invalid"]},
        {"links": ["https://example.invalid/" + "x" * 2048]},
        {"state": "verified"},
        {"event_kind": "execution", "state": "remediated"},
        {"due_date": "2026-02-30"},
        {"expected_previous_event": str(uuid4())},
        {"authority": "provider_write"},
    ],
)
def test_actual_sql_admission_rejects_null_bounds_and_unsupported_claims(
    decision_context, changes
):
    with pytest.raises(DatabaseError):
        raw_issue(decision_context, envelope(decision_context, **changes))
    assert not DecisionEvent.objects.exists()


def test_raw_runtime_writes_and_owner_only_selection_denied(decision_context):
    first = decide(decision_context)
    for alias in ("app_runtime", "worker_runtime"):
        with pytest.raises(DatabaseError), transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    "UPDATE core_decision_events SET state=%s WHERE id=%s",
                    ["verified", first],
                )
        with pytest.raises(DatabaseError), transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    "SELECT app_private.selected_core_decisions(%s,%s)",
                    [decision_context[2].id, decision_context[1].id],
                )
        with connections[alias].cursor() as cursor:
            cursor.execute(
                "SELECT has_table_privilege(current_user,"
                "'core_decision_events','INSERT'),"
                "has_table_privilege(current_user,'core_decision_events','DELETE'),"
                "has_table_privilege(current_user,'core_decision_desk_gate','UPDATE')"
            )
            assert cursor.fetchone() == (False, False, False)
    with pytest.raises(DatabaseError):
        raw_issue(decision_context, envelope(decision_context), alias="worker_runtime")


def test_stale_cas_and_cross_tenant_never_append(decision_context):
    first = decide(decision_context)
    with pytest.raises(DatabaseError):
        decide(decision_context, state="decline")
    with pytest.raises(DatabaseError):
        decide(
            decision_context,
            organization_id=Organization.objects.create(name="Other tenant").id,
        )
    assert DecisionEvent.objects.count() == 1
    assert selected(decision_context)[0]["event_id"] == str(first)


def test_pause_denies_new_decisions(decision_context):
    user, org, _, _ = decision_context
    configure_control(
        organization_id=org.id,
        actor_id=user.id,
        mode="paused",
        reason="Owner pause",
        using="app_runtime",
    )
    with pytest.raises(DatabaseError):
        decide(decision_context)
    assert not DecisionEvent.objects.exists()


def test_past_due_subscription_retains_current_issued_coverage_authority(
    decision_context,
):
    from apps.billing.models import Subscription

    Subscription.objects.filter(organization=decision_context[1]).update(
        status=Subscription.Status.PAST_DUE
    )
    event = decide(decision_context)
    assert DecisionEvent.objects.get(pk=event).state == "act"


def test_same_tenant_viewer_cannot_read_or_issue_owner_decisions(decision_context):
    from django.contrib.auth import get_user_model

    from apps.organizations.models import OrganizationMember

    first = decide(decision_context)
    viewer = get_user_model().objects.create_user("decision-viewer@example.invalid")
    org = decision_context[1]
    OrganizationMember.objects.create(organization=org, user=viewer, role="viewer")
    with (
        identity_transaction(viewer.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        with connections["app_runtime"].cursor() as cursor:
            cursor.execute("SELECT id FROM core_decision_events WHERE id=%s", [first])
            assert cursor.fetchall() == []
    with pytest.raises(DatabaseError):
        decide(decision_context, actor_id=viewer.id)
    assert DecisionEvent.objects.count() == 1


def test_two_simultaneous_first_events_have_one_cas_winner(decision_context):
    barrier = Barrier(2)

    def contender(state):
        try:
            barrier.wait(timeout=10)
            return ("accepted", decide(decision_context, state=state))
        except DatabaseError:
            return ("denied", None)
        finally:
            connections["app_runtime"].close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(contender, ["act", "defer"]))
    assert sorted(row[0] for row in outcomes) == ["accepted", "denied"]
    assert DecisionEvent.objects.count() == 1


def test_no_carry_forward_to_other_snapshot_or_tenant(decision_context, report_context):
    from datetime import timedelta

    from conftest import _roi_inputs

    from apps.assessments.snapshots import create_assessment_snapshot

    decide(decision_context)
    user, org, snapshot, _ = decision_context
    item = report_context[3]
    item.display_name = "Changed payroll workflow"
    item.save(update_fields=["display_name"])
    changed = create_assessment_snapshot(
        organization_id=org.id,
        created_by_id=user.id,
        assessed_item_id=item.id,
        roi_inputs=_roi_inputs(),
        captured_at=snapshot.captured_at + timedelta(days=1),
        previous_snapshot=snapshot,
    )
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        with connections["app_runtime"].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.issue_action_cards(%s,%s,%s,%s)",
                [uuid4(), org.id, user.id, changed.id],
            )
    assert selected(decision_context, snapshot=changed.id) == []
    assert selected(decision_context, snapshot=uuid4()) == []
    assert (
        selected(
            decision_context,
            org=Organization.objects.create(name="Unrelated tenant").id,
        )
        == []
    )


def test_frozen_pack_replay_retains_selected_event_when_current_decision_changes(
    decision_context,
):
    from apps.reviews.services import freeze_cycle, open_cycle

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
    assert pack.manifest["selected_decisions"][0]["event_id"] == str(first)
    second = decide(decision_context, expected_previous_event=first, state="defer")
    assert selected(decision_context)[0]["event_id"] == str(second)
    replay = freeze_cycle(
        cycle_id=cycle.id,
        organization_id=org.id,
        actor_id=user.id,
        expected_revision=1,
        using="app_runtime",
    )
    assert replay.id == pack.id
    assert replay.sha256 == pack.sha256
    assert replay.manifest["selected_decisions"][0]["event_id"] == str(first)
