"""Proposed actual-role successor tests; pending artifact, not executed evidence.

The capture denial is expected to fail against the unfenced predecessor and
pass after jobs0015. Run both pinned candidates to preserve the counterexample.
"""

import importlib
from uuid import uuid4

import pytest
from django.db import DatabaseError, connections

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.jobs.core_models import ActionCardRevision
from apps.organizations.models import WorkflowProfile
from tests.test_capture_admission import admit, preview
from tests.test_capture_admission import capture_context as capture_context
from tests.test_explicit_inventory import explicit_context as explicit_context

__all__ = ["capture_context", "explicit_context"]
pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


def issue_raw(context, snapshot_id, *, using="app_runtime"):
    user, org = context[:2]
    with (
        identity_transaction(user.id, using=using),
        tenant_transaction(org.id, using=using),
        connections[using].cursor() as cursor,
    ):
        cursor.execute(
            "SELECT app_private.issue_action_cards(%s,%s,%s,%s)",
            [uuid4(), org.id, user.id, snapshot_id],
        )
        return cursor.fetchone()[0]


def test_direct_app_sql_cannot_issue_legacy_cards_for_admitted_capture2(
    capture_context,
):
    snapshot = admit(capture_context, preview(capture_context))
    with pytest.raises(DatabaseError, match="snapshot schema one"):
        issue_raw(capture_context, snapshot.id)
    assert not ActionCardRevision.objects.filter(snapshot=snapshot).exists()


def test_direct_app_sql_unresolved_snapshot_cannot_bypass_schema_dispatch(
    capture_context,
):
    with pytest.raises(DatabaseError, match="snapshot schema one"):
        issue_raw(capture_context, uuid4())
    assert ActionCardRevision.objects.count() == 0


def test_schema1_issuance_and_exact_replay_keep_legacy_meaning(report_context):
    user, org, _, _, snapshot = report_context
    WorkflowProfile.objects.get_or_create(
        organization=org,
        defaults={
            "created_by": user,
            "profile": "business.v1",
            "settings": {"name": "Legacy comparison"},
        },
    )
    first = issue_raw(report_context, snapshot.id)
    second = issue_raw(report_context, snapshot.id)
    assert first == second
    revision = ActionCardRevision.objects.get(id=first)
    assert revision.input_sha256 == snapshot.result_sha256
    assert all(card["authority"] == "proposal_only" for card in revision.cards)
    assert not any("source_class" in card for card in revision.cards)


@pytest.mark.parametrize("using", ["app_runtime", "worker_runtime"])
def test_renamed_legacy_delegate_is_not_an_app_or_worker_bypass(using):
    with connections[using].cursor() as cursor:
        cursor.execute(
            "SELECT has_function_privilege(current_user,%s,'EXECUTE')",
            ["app_private.issue_action_cards_schema1(uuid,uuid,uuid,uuid)"],
        )
        assert cursor.fetchone() == (False,)


def test_worker_cannot_execute_public_legacy_issuer(capture_context):
    snapshot = admit(capture_context, preview(capture_context))
    with pytest.raises(DatabaseError, match="permission denied"):
        issue_raw(capture_context, snapshot.id, using="worker_runtime")
    assert not ActionCardRevision.objects.filter(snapshot=snapshot).exists()


def test_renamed_schema1_delegate_body_and_searchpath_are_preserved():
    predecessor = importlib.import_module(
        "apps.jobs.migrations.0012_core_authority_successor"
    ).SQL
    start = predecessor.index(
        "CREATE OR REPLACE FUNCTION app_private.issue_action_cards"
    )
    start = predecessor.index("AS $fn$", start) + len("AS $fn$")
    end = predecessor.index("$fn$;", start)
    expected_body = predecessor[start:end]
    with connections["default"].cursor() as cursor:
        cursor.execute(
            "SELECT p.prosrc,p.proconfig,r.rolname FROM pg_proc p "
            "JOIN pg_roles r ON r.oid=p.proowner WHERE p.oid=%s::regprocedure",
            ["app_private.issue_action_cards_schema1(uuid,uuid,uuid,uuid)"],
        )
        body, configuration, owner = cursor.fetchone()
    assert body == expected_body
    assert configuration == ["search_path=pg_catalog, public"]
    assert owner == "agentledger_owner"


@pytest.mark.parametrize("lookup", ["existing_capture", "unresolved"])
def test_wrong_app_context_is_rejected_before_definer_snapshot_lookup(
    capture_context, lookup
):
    user, org = capture_context
    snapshot = admit(capture_context, preview(capture_context))
    selected_snapshot = snapshot.id if lookup == "existing_capture" else uuid4()
    with pytest.raises(DatabaseError, match="Action-card context binding invalid"):
        with (
            identity_transaction(user.id, using="app_runtime"),
            tenant_transaction(org.id, using="app_runtime"),
            connections["app_runtime"].cursor() as cursor,
        ):
            cursor.execute(
                "SELECT app_private.issue_action_cards(%s,%s,%s,%s)",
                [uuid4(), uuid4(), user.id, selected_snapshot],
            )
    assert not ActionCardRevision.objects.filter(snapshot=snapshot).exists()
