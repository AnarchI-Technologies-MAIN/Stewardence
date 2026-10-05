"""Actual-role v4 freeze and projection; PDF delivery is qualified separately."""

import json
from uuid import uuid4

import pytest
from django.db import DatabaseError, connections

from agentledger.tenancy.context import tenant_transaction
from apps.reviews.capture_context_v3 import build_capture_v4_pack_context
from apps.reviews.models import ReviewLifecycleGate
from apps.reviews.services import freeze_cycle, open_cycle
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_capture_decisions import (
    capture_decision_context as capture_decision_context,
)
from tests.test_capture_decisions import decide
from tests.test_capture_pack_authority import requested
from tests.test_explicit_inventory import explicit_context as explicit_context
from tests.test_review_pack_lifecycle import claimed

__all__ = ["capture_context", "capture_decision_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def frozen(context):
    user, org, snapshot = context[:3]
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


def replay(context):
    user, org, _, pack = context
    return freeze_cycle(
        cycle_id=pack.cycle_id,
        organization_id=org.id,
        actor_id=user.id,
        expected_revision=1,
        using="app_runtime",
    )


@pytest.fixture
def lifecycle(settings):
    settings.REVIEW_PACK_LIFECYCLE_ENABLED = True
    ReviewLifecycleGate.objects.update_or_create(id=1, defaults={"enabled": True})


def test_v4_freezes_all_issued_proposals_without_claiming_statements(
    capture_decision_context,
):
    context = frozen(capture_decision_context)
    manifest = context[3].manifest
    assert len(manifest) == 12
    assert manifest["schema"] == "stewardence.review_pack.v4"
    assert (
        manifest["proposal_contract_version"] == "stewardence.core_review_proposal.v1"
    )
    assert manifest["selection_scope"] == "issued_capture_proposals"
    assert manifest["selected_decisions"] == []
    assert manifest["baseline_pack_id"] is None
    assert manifest["baseline_promotion"] == "blocked"
    assert [
        entry["proposal"] for entry in manifest["selected_proposals"]
    ] == capture_decision_context[3].cards
    assert all(len(entry) == 7 for entry in manifest["selected_proposals"])
    assert replay(context).manifest == manifest


def test_disposition_and_execution_freeze_independently_and_replay_old_history(
    capture_decision_context,
):
    first = decide(capture_decision_context, event_kind="disposition", state="defer")
    execution = decide(capture_decision_context, expected_previous_event=str(first))
    context = frozen(capture_decision_context)
    selected = context[3].manifest["selected_decisions"]
    assert {entry["event_id"] for entry in selected} == {
        str(first),
        str(execution),
    }
    assert {entry["payload"]["event_kind"] for entry in selected} == {
        "disposition",
        "execution",
    }
    later = decide(
        capture_decision_context,
        event_kind="disposition",
        state="act",
        expected_previous_event=str(execution),
    )
    assert str(later) not in {entry["event_id"] for entry in selected}
    assert replay(context).manifest["selected_decisions"] == selected
    assert all(entry["payload"]["resolution_verified"] is False for entry in selected)


def test_v3_replay_never_changes_when_proposals_are_issued_later(
    capture_context, settings
):
    from apps.reviews.models import CoreProposalAdmissionGate
    from apps.reviews.proposal_admission import issue_capture_proposals

    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    context = frozen((user, org, snapshot))
    before = context[3].manifest
    assert before["schema"] == "stewardence.review_pack.v3"
    settings.CORE_PROPOSAL_ADMISSION_ENABLED = True
    CoreProposalAdmissionGate.objects.update_or_create(id=1, defaults={"enabled": True})
    issue_capture_proposals(
        organization_id=org.id,
        actor_id=user.id,
        snapshot_id=snapshot.id,
        using="app_runtime",
    )
    assert replay(context).manifest == before


def test_exact_preflight_matches_permanent_context_and_actual_worker_projection(
    capture_decision_context, lifecycle
):
    decide(capture_decision_context, notes="Owner statement <script>literal</script>")
    context = frozen(capture_decision_context)
    request = requested(context)
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT app_private.capture_proposal_preflight_context(%s)", [request.id]
        )
        value = cursor.fetchone()[0]
    sql_context = json.loads(value) if isinstance(value, str) else value
    python_context = build_capture_v4_pack_context(
        sql_context["metadata"], sql_context["projection"]
    )
    assert sql_context == python_context
    encoded = json.dumps(
        python_context, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT octet_length(convert_to(app_private.queue_canonical("
            "app_private.capture_proposal_preflight_context(%s)),'UTF8'))",
            [request.id],
        )
        assert cursor.fetchone()[0] == len(encoded)
    job = claimed(context)
    with (
        tenant_transaction(job.organization_id, using="worker_runtime"),
        connections["worker_runtime"].cursor() as cursor,
    ):
        cursor.execute(
            "SELECT app_private.review_pack_projection(%s,%s)",
            [job.id, job.claim_token],
        )
        value = cursor.fetchone()[0]
    projection = json.loads(value) if isinstance(value, str) else value
    assert len(projection) == 12
    assert projection == sql_context["projection"]
    assert projection["schema"] == "stewardence.review_worker_projection.v3"
    with pytest.raises(DatabaseError):
        with (
            tenant_transaction(job.organization_id, using="worker_runtime"),
            connections["worker_runtime"].cursor() as cursor,
        ):
            cursor.execute(
                "SELECT app_private.review_pack_projection(%s,%s)", [job.id, uuid4()]
            )


@pytest.mark.parametrize("using", ["app_runtime", "worker_runtime"])
def test_private_v4_issuers_and_preflight_are_not_role_authority(using):
    signatures = [
        "app_private.freeze_review_cycle_pre_v4(uuid,uuid,uuid,integer)",
        "app_private.freeze_capture_proposal_review_cycle(uuid,uuid,uuid,integer)",
        "app_private.review_capture_proposal_selection_v1(uuid,uuid)",
        "app_private.review_capture_decision_selection_v2(uuid,uuid)",
        "app_private.capture_proposal_request_projection(uuid)",
        "app_private.capture_proposal_preflight_context(uuid)",
        "app_private.capture_proposal_pack_projection(uuid,uuid)",
    ]
    with connections[using].cursor() as cursor:
        for signature in signatures:
            cursor.execute(
                "SELECT has_function_privilege(current_user,%s,'EXECUTE')", [signature]
            )
            assert cursor.fetchone() == (False,)


def test_v4_request_cannot_authorize_baseline(capture_decision_context, lifecycle):
    from apps.reports.models import Report
    from apps.reviews.models import ArtifactRequest

    context = frozen(capture_decision_context)
    before = Report.objects.count()
    with pytest.raises(DatabaseError):
        requested(context, promote_baseline=True)
    assert Report.objects.count() == before
    assert not ArtifactRequest.objects.exists()


def test_second_owner_cannot_reassign_original_capture_creator(
    capture_decision_context,
    lifecycle,
):
    from django.contrib.auth import get_user_model

    from apps.organizations.models import OrganizationMember
    from apps.reviews.models import ArtifactRequest, PackIdentity
    from apps.reviews.services import request_pack_artifact

    original, org, snapshot, _ = capture_decision_context
    second = get_user_model().objects.create_user(
        "second-pack-owner@example.invalid",
        password="qualification-password",
    )
    OrganizationMember.objects.create(organization=org, user=second, role="owner")
    # The admitted billing model binds its single organizational subscription
    # to one customer user. Do not fabricate dual paid authority or transfer
    # immutable billing identities to reach the creator predicate.
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT app_private.core_owner_entitled(%s,%s)",
            [org.id, second.id],
        )
        assert cursor.fetchone() == (False,)
        cursor.execute(
            "SELECT app_private.require_capture_pack_creator(%s,%s,%s)",
            [snapshot.id, org.id, original.id],
        )
    with pytest.raises(DatabaseError, match="original admitted creator"):
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.require_capture_pack_creator(%s,%s,%s)",
                [snapshot.id, org.id, second.id],
            )
    before = PackIdentity.objects.count()
    with pytest.raises(DatabaseError):
        frozen((second, org, snapshot))
    assert PackIdentity.objects.count() == before
    context = frozen(capture_decision_context)
    with pytest.raises(DatabaseError):
        request_pack_artifact(
            pack_id=context[3].id,
            organization_id=org.id,
            actor_id=second.id,
            using="app_runtime",
        )
    assert not ArtifactRequest.objects.exists()
