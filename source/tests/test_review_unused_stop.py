"""Unused-only stop releases held capacity, never admitted or ambiguous work."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from time import monotonic, sleep
from uuid import UUID, uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connections

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.billing.models import Subscription
from apps.jobs.core_workflows import configure_control
from apps.reports.models import Report
from apps.reports.services import create_report
from apps.reviews.models import (
    ArtifactRequest,
    CapacityReservation,
    CoreProposalAdmissionGate,
    CycleEvent,
    ReservationEvent,
    UnusedStopGate,
)
from apps.reviews.unused_stop import stop_unused_pack
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_capture_pack_authority import requested
from tests.test_capture_v4_packs import frozen
from tests.test_capture_v4_packs import lifecycle as lifecycle
from tests.test_explicit_inventory import explicit_context as explicit_context

__all__ = [
    "capture_context",
    "capture_decision_context",
    "explicit_context",
    "lifecycle",
]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def _proposal_failure_facts(context, snapshot):
    """Post-rollback observations; cannot establish earlier issuer-time state."""
    user, org = context
    facts = {
        "scope": "post_rollback_observation_not_issuer_time",
        "python_clock": datetime.now(UTC).isoformat(),
    }
    try:
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
            connections["app_runtime"].cursor() as cursor,
        ):
            cursor.execute(
                "SELECT jsonb_build_object('clock',clock_timestamp(),"
                "'session_role',session_user,'isolation',current_setting('transaction_isolation'),"
                "'actor_matches',app_private.current_user_id()=%s,"
                "'tenant_matches',app_private.current_organization_id()=%s)",
                [user.id, org.id],
            )
            facts["same_app_connection_new_context"] = cursor.fetchone()[0]
        with connections["default"].cursor() as cursor:
            cursor.execute(
                """
                SELECT jsonb_build_object('clock',clock_timestamp(),
                'owner_entitled',app_private.core_owner_entitled(%s,%s),
                'work_allowed',app_private.core_work_allowed(%s),
                'owner_membership',EXISTS(
                    SELECT 1 FROM organizations_organizationmember
                    WHERE organization_id=%s AND user_id=%s AND role='owner'),
                'profile_exists',EXISTS(
                    SELECT 1 FROM organization_workflow_profiles
                    WHERE organization_id=%s),
                'proposal_gate',coalesce((SELECT enabled
                    FROM review_core_proposal_gate WHERE id=1),false),
                'pause_present',EXISTS(SELECT 1 FROM core_health_controls h
                    WHERE organization_id=%s AND mode='paused'
                    AND NOT EXISTS(SELECT 1 FROM core_health_controls n
                        WHERE n.supersedes_id=h.id)),
                'snapshot_creator_matches',(SELECT created_by_id=%s
                    FROM assessment_snapshots WHERE id=%s),
                'capture_creator_matches',(SELECT created_by_id=%s
                    FROM assessment_capture_receipts WHERE snapshot_id=%s),
                'captured_at',(SELECT captured_at
                    FROM assessment_snapshots WHERE id=%s),
                'not_future',(SELECT captured_at<=clock_timestamp()
                    FROM assessment_snapshots WHERE id=%s),
                'subscriptions',coalesce((SELECT jsonb_agg(jsonb_build_object(
                    'status',s.status,'portfolio',s.portfolio,
                    'paid_access',app_private.paid_subscription_access(s.id),
                    'coverage',coalesce((SELECT jsonb_agg(jsonb_build_object(
                        'start',p.service_start,'end',p.service_end,
                        'current',p.service_start<=clock_timestamp()
                            AND p.service_end>clock_timestamp()))
                        FROM billing_paid_coverage p
                        WHERE p.subscription_id=s.id),'[]'::jsonb)))
                    FROM billing_subscription s
                    WHERE s.organization_id=%s),'[]'::jsonb))
                """,
                [
                    org.id,
                    user.id,
                    org.id,
                    org.id,
                    user.id,
                    org.id,
                    org.id,
                    user.id,
                    snapshot.id,
                    user.id,
                    snapshot.id,
                    snapshot.id,
                    snapshot.id,
                    org.id,
                ],
            )
            facts["operator_predicate_observation"] = cursor.fetchone()[0]
    except Exception as diagnostic_error:
        facts["diagnostic_error_type"] = type(diagnostic_error).__name__
    return facts


@pytest.fixture
def capture_decision_context(capture_context, settings, request):
    """Same fixture admission; diagnostics execute only after its exception."""
    import json

    from apps.jobs.core_models import DecisionDeskGate
    from apps.reviews.proposal_admission import issue_capture_proposals

    settings.CORE_PROPOSAL_ADMISSION_ENABLED = True
    settings.DECISION_DESK_ENABLED = True
    CoreProposalAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})
    DecisionDeskGate.objects.update_or_create(id=1, defaults={"enabled": True})
    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    try:
        revision = issue_capture_proposals(
            organization_id=org.id,
            actor_id=user.id,
            snapshot_id=snapshot.id,
            using="app_runtime",
        )
    except DatabaseError as error:
        facts = json.dumps(
            _proposal_failure_facts(capture_context, snapshot),
            default=str,
            sort_keys=True,
        )
        request.node.add_report_section(
            "setup", "proposal authority diagnostics", facts
        )
        error.add_note(
            "Qualification-only post-rollback proposal diagnostics: " + facts
        )
        raise
    return user, org, snapshot, revision


@pytest.fixture
def unused_pack(capture_decision_context, settings):
    settings.REVIEW_UNUSED_STOP_ENABLED = True
    UnusedStopGate.objects.update_or_create(id=1, defaults={"enabled": True})
    return frozen(capture_decision_context)


def stop(context, *, reason="owner_stopped"):
    user, org, _, pack = context
    return stop_unused_pack(
        pack_id=pack.id,
        organization_id=org.id,
        actor_id=user.id,
        reason=reason,
        using="app_runtime",
    )


def test_stop_receipt_replay_keeps_evidence_and_monthly_admission(unused_pack):
    user, org, _, pack = unused_pack
    reservation = CapacityReservation.objects.get(cycle_id=pack.cycle_id)
    before = pack.manifest
    event = stop(unused_pack, reason="context_too_large")
    assert event.state == "TERMINATED_UNUSED" and event.revision == 4
    assert len(event.payload) == 11
    assert event.payload["schema"] == "stewardence.review_unused_stop.v1"
    assert event.payload["proof_scope"] == "no_admitted_report_work"
    assert event.payload["monthly_allowance_refunded"] is False
    assert stop(unused_pack, reason="context_too_large").id == event.id
    with (
        identity_transaction(user.id, using="app_runtime"),
        tenant_transaction(org.id, using="app_runtime"),
    ):
        pack.refresh_from_db()
    reservation.refresh_from_db()
    assert pack.manifest == before and reservation.state == "reserved"
    assert CapacityReservation.objects.filter(organization=org).count() == 1
    latest = ReservationEvent.objects.filter(reservation=reservation).latest("revision")
    assert latest.state == "proven_unused" and latest.revision == 2
    assert latest.payload["stop_event_id"] == str(event.id)
    assert CycleEvent.objects.filter(cycle_id=pack.cycle_id).count() == 4
    with pytest.raises(DatabaseError, match="replay changed"):
        stop(unused_pack)


def test_paid_expiry_and_pause_do_not_remove_unused_owner_stop(unused_pack):
    user, org, _, _ = unused_pack
    configure_control(
        organization_id=org.id,
        actor_id=user.id,
        mode="paused",
        reason="Owner stop",
        using="app_runtime",
    )
    Subscription.objects.filter(organization=org).update(status="canceled")
    assert stop(unused_pack).state == "TERMINATED_UNUSED"


def test_fresh_capture_freezes_after_stop_without_refunding_monthly_slot(unused_pack):
    user, org, _, _ = unused_pack
    stop(unused_pack)
    from apps.reviews.proposal_admission import issue_capture_proposals

    snapshot = admit((user, org), preview((user, org)))
    revision = issue_capture_proposals(
        organization_id=org.id,
        actor_id=user.id,
        snapshot_id=snapshot.id,
        using="app_runtime",
    )
    next_context = frozen((user, org, snapshot, revision))
    assert next_context[3].manifest["schema"] == "stewardence.review_pack.v4"
    assert CapacityReservation.objects.filter(organization=org).count() == 2


def test_terminated_snapshot_cannot_admit_report_or_request(unused_pack, lifecycle):
    user, org, snapshot, _ = unused_pack
    stop(unused_pack)
    with pytest.raises(DatabaseError, match="terminated capture"):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
        ):
            create_report(
                organization_id=org.id,
                assessment_snapshot_id=snapshot.id,
                created_by_id=user.id,
                using="app_runtime",
            )
    with pytest.raises(DatabaseError, match="terminated capture"):
        requested(unused_pack)
    assert not Report.objects.filter(assessment_snapshot=snapshot).exists()
    assert not ArtifactRequest.objects.exists()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_capture_report_cannot_use_pretermination_snapshot_authority(
    unused_pack, isolation
):
    from django.db import transaction

    user, org, snapshot, _ = unused_pack
    with pytest.raises(DatabaseError, match="requires read committed"):
        with transaction.atomic(using="app_runtime"):
            with connections["app_runtime"].cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL " + isolation)
            with (
                identity_transaction(user.id, using="app_runtime"),
                tenant_transaction(org.id, using="app_runtime"),
            ):
                create_report(
                    organization_id=org.id,
                    assessment_snapshot_id=snapshot.id,
                    created_by_id=user.id,
                    using="app_runtime",
                )
    assert not Report.objects.filter(assessment_snapshot=snapshot).exists()


@pytest.mark.parametrize("existing", ["report", "request"])
def test_any_admitted_report_work_is_ineligible(unused_pack, lifecycle, existing):
    user, org, snapshot, _ = unused_pack
    if existing == "report":
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
        ):
            create_report(
                organization_id=org.id,
                assessment_snapshot_id=snapshot.id,
                created_by_id=user.id,
                using="app_runtime",
            )
    if existing == "request":
        requested(unused_pack)
    with pytest.raises(DatabaseError, match="admitted or ambiguous"):
        stop(unused_pack)
    assert not CycleEvent.objects.filter(state="TERMINATED_UNUSED").exists()
    assert not ReservationEvent.objects.filter(state="proven_unused").exists()


def test_stop_request_race_commits_exactly_one_outcome(unused_pack, lifecycle):
    start = Barrier(2)

    def attempt(operation):
        connections.close_all()
        start.wait(timeout=15)
        try:
            result = operation(unused_pack)
            return "admitted", result.id
        except DatabaseError as error:
            return "denied", None, str(error)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        stopping = pool.submit(attempt, stop)
        requesting = pool.submit(attempt, requested)
        outcomes = [stopping.result(timeout=30), requesting.result(timeout=30)]
    assert sorted(value[0] for value in outcomes) == ["admitted", "denied"]
    stopped = CycleEvent.objects.filter(state="TERMINATED_UNUSED").exists()
    assert ArtifactRequest.objects.exists() is not stopped
    assert ReservationEvent.objects.filter(state="proven_unused").exists() is stopped


@pytest.mark.parametrize("gate", ["application", "operator"])
def test_closed_stop_gate_has_no_effects(unused_pack, settings, gate):
    if gate == "application":
        settings.REVIEW_UNUSED_STOP_ENABLED = False
        with pytest.raises(ValidationError):
            stop(unused_pack)
    if gate == "operator":
        UnusedStopGate.objects.filter(id=1).update(enabled=False)
        with pytest.raises(DatabaseError, match="authority unavailable"):
            stop(unused_pack)
    assert not CycleEvent.objects.filter(state="TERMINATED_UNUSED").exists()


@pytest.mark.parametrize("using", ["app_runtime", "worker_runtime"])
def test_raw_receipt_and_gate_mutations_are_denied(unused_pack, using):
    user, org, _, pack = unused_pack
    with pytest.raises(DatabaseError):
        with (
            identity_transaction(user.id, using=using),
            tenant_transaction(org.id, using=using),
            connections[using].cursor() as cursor,
        ):
            cursor.execute(
                "INSERT INTO review_cycle_events(id,organization_id,created_by_id,"
                "created_at,cycle_id,revision,state,payload,sha256) VALUES"
                "(%s,%s,%s,clock_timestamp(),%s,4,'TERMINATED_UNUSED','{}',%s)",
                [uuid4(), org.id, user.id, pack.cycle_id, "0" * 64],
            )
    with pytest.raises(DatabaseError):
        with connections[using].cursor() as cursor:
            cursor.execute("UPDATE review_unused_stop_gate SET enabled=true WHERE id=1")
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE')",
            ["app_private.stop_unused_review_pack(uuid,uuid,uuid,text)"],
        )
        assert cursor.fetchone() == (using == "app_runtime",)


@pytest.mark.parametrize("first", ["stop", "report"])
def test_snapshot_wait_orders_report_admission_against_unused_proof(unused_pack, first):
    """Queue both actual app logins on an operator-held snapshot row."""
    from django.db import transaction

    user, org, snapshot, _ = unused_pack
    names = {
        kind: "unused-row-race-" + kind + uuid4().hex for kind in ("stop", "report")
    }

    def attempt(kind):
        connections.close_all()
        try:
            with connections["app_runtime"].cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('application_name',%s,false)", [names[kind]]
                )
            if kind == "stop":
                return "admitted", stop(unused_pack).id
            with (
                identity_transaction(user.id, using="app_runtime"),
                tenant_transaction(org.id, using="app_runtime"),
            ):
                result = create_report(
                    organization_id=org.id,
                    assessment_snapshot_id=snapshot.id,
                    created_by_id=user.id,
                    using="app_runtime",
                )
                return "admitted", result.id
        except DatabaseError as error:
            return "denied", None, str(error)
        finally:
            connections.close_all()

    def require_wait(kind, future):
        deadline = monotonic() + 15
        while monotonic() < deadline:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT pg_stat_clear_snapshot()")
                cursor.execute(
                    "SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE "
                    "application_name=%s AND wait_event_type='Lock')",
                    [names[kind]],
                )
                if cursor.fetchone()[0]:
                    return
            if future.done():
                pytest.fail(
                    f"Actual {kind} login exited before barrier: {future.result()}"
                )
            sleep(0.025)
        pytest.fail(f"Actual {kind} login never reached row-lock barrier")

    second = "report" if first == "stop" else "stop"
    with ThreadPoolExecutor(max_workers=2) as pool:
        with transaction.atomic(), connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT id FROM assessment_snapshots WHERE id=%s FOR UPDATE",
                [snapshot.id],
            )
            first_future = pool.submit(attempt, first)
            require_wait(first, first_future)
            second_future = pool.submit(attempt, second)
            require_wait(second, second_future)
        assert first_future.result(timeout=30)[0] == "admitted"
        assert second_future.result(timeout=30)[0] == "denied"
    stopped = CycleEvent.objects.filter(state="TERMINATED_UNUSED").exists()
    assert stopped is (first == "stop")
    assert Report.objects.filter(assessment_snapshot=snapshot).exists() is not stopped


def test_admitted_unicode_notes_exceed_context_and_unused_stop_recovers_capacity(
    capture_decision_context,
    lifecycle,
    settings,
):
    """Four real records and 32 issued owner statements, no raw fake events."""
    from apps.jobs.core_decisions_v2 import record_capture_decision
    from apps.jobs.models import BackgroundJob
    from apps.reviews.proposal_admission import issue_capture_proposals
    from tests.test_explicit_inventory import issue

    user, org = capture_decision_context[:2]
    settings.REVIEW_UNUSED_STOP_ENABLED = True
    UnusedStopGate.objects.update_or_create(id=1, defaults={"enabled": True})
    for _ in range(3):
        issue((user, org))
    snapshot = admit((user, org), preview((user, org)))
    assert len(snapshot.input_payload["inventory"]) == 4
    revision = issue_capture_proposals(
        organization_id=org.id,
        actor_id=user.id,
        snapshot_id=snapshot.id,
        using="app_runtime",
    )
    assert len(revision.cards) == 16
    notes = "\U0001f9f0" * 4096
    for index, proposal in enumerate(revision.cards):
        prior = None
        for kind, state in (
            ("disposition", "defer"),
            ("execution", "completion_recorded"),
        ):
            prior = record_capture_decision(
                organization_id=org.id,
                actor_id=user.id,
                revision_id=revision.id,
                proposal_id=UUID(proposal["proposal_id"]),
                proposal_sha256=proposal["sha256"],
                card_index=index,
                event_kind=kind,
                state=state,
                responsible_label="Named owner",
                expected_previous_event=prior,
                notes=notes,
                using="app_runtime",
            )
    context = frozen((user, org, snapshot, revision))
    assert len(context[3].manifest["selected_decisions"]) == 32
    assert all(
        entry["payload"]["notes"] == notes
        for entry in context[3].manifest["selected_decisions"]
    )
    reports_before = Report.objects.count()
    jobs_before = BackgroundJob.objects.count()
    # The existing canonicalizer checks jsonb::text before emitting compact
    # RFC8785. Qualify both sizes and its exact earlier failure; don't pretend
    # the later renderer-specific size check executed.
    import json

    with pytest.raises(DatabaseError, match="Queue input exceeds admission bounds"):
        requested(context)
    assert Report.objects.count() == reports_before
    assert BackgroundJob.objects.count() == jobs_before
    assert not ArtifactRequest.objects.exists()
    # Allocate no new production effects merely to compute the context. The
    # frozen manifest already duplicates its selected statement bytes in the
    # final projection: each copy is 32 * 4096 * 4 bytes before structure.
    selected_bytes = len(
        json.dumps(
            context[3].manifest["selected_decisions"],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )
    assert selected_bytes > 32 * 4096 * 4
    assert selected_bytes * 2 > 1048576
    assert stop(context, reason="context_too_large").state == "TERMINATED_UNUSED"
    fresh = admit((user, org), preview((user, org)))
    fresh_revision = issue_capture_proposals(
        organization_id=org.id,
        actor_id=user.id,
        snapshot_id=fresh.id,
        using="app_runtime",
    )
    assert (
        frozen((user, org, fresh, fresh_revision))[3].manifest["schema"]
        == "stewardence.review_pack.v4"
    )
    assert CapacityReservation.objects.filter(organization=org).count() == 2


@pytest.mark.parametrize("identity", ["viewer", "foreign"])
def test_membership_and_context_not_paid_state_are_stop_authority(
    unused_pack, identity
):
    from django.contrib.auth import get_user_model

    from apps.organizations.models import Organization, OrganizationMember

    user, org, _, pack = unused_pack
    actor = user
    target_org = org
    if identity == "viewer":
        actor = get_user_model().objects.create_user("unused-viewer@example.invalid")
        OrganizationMember.objects.create(organization=org, user=actor, role="viewer")
    if identity == "foreign":
        target_org = Organization.objects.create(name="Other unused owner")
        OrganizationMember.objects.create(
            organization=target_org, user=actor, role="owner"
        )
    with pytest.raises(DatabaseError):
        stop_unused_pack(
            pack_id=pack.id,
            organization_id=target_org.id,
            actor_id=actor.id,
            reason="owner_stopped",
            using="app_runtime",
        )
    assert not CycleEvent.objects.filter(state="TERMINATED_UNUSED").exists()
