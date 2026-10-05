import os
from datetime import timedelta

import pytest
from django.db import DatabaseError
from django.utils import timezone

from agentledger.tenancy.context import (
    activate_tenant,
    identity_transaction,
    tenant_transaction,
)
from apps.accounts.models import User
from apps.integrations.models import (
    QuickBooksAttempt,
    QuickBooksConnection,
    QuickBooksEvent,
)
from apps.organizations.models import Organization, OrganizationMember

pytestmark = [
    pytest.mark.rls,
    pytest.mark.skipif(
        os.getenv("AGENTLEDGER_RLS_TESTS") != "1",
        reason="PostgreSQL restricted-role harness required",
    ),
    pytest.mark.django_db(
        transaction=True, databases={"default", "app_runtime", "worker_runtime"}
    ),
]


@pytest.fixture
def rows():
    result = []
    for index in range(2):
        user = User.objects.create_user(f"qbo-rls-{index}@example.com")
        org = Organization.objects.create(name=f"QBO sandbox {index}")
        OrganizationMember.objects.create(user=user, organization=org, role="owner")
        obj = QuickBooksConnection.objects.create(organization=org, connected_by=user)
        attempt = QuickBooksAttempt.objects.create(
            connection=obj,
            state_hash=str(index) * 64,
            session_hash="a" * 64,
            generation=0,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        event = QuickBooksEvent.objects.create(
            connection=obj, kind="authorization_started"
        )
        result.append((user, org, obj, attempt, event))
    return result


def test_runtime_reads_only_connecting_owner_and_active_tenant(rows):
    user, org, obj, attempt, event = rows[0]
    with identity_transaction(user.id, using="app_runtime"):
        activate_tenant(org.id, using="app_runtime")
        for model, expected in [
            (QuickBooksConnection, obj),
            (QuickBooksAttempt, attempt),
            (QuickBooksEvent, event),
        ]:
            assert list(
                model.objects.using("app_runtime").values_list("id", flat=True)
            ) == [expected.id]
        assert (
            QuickBooksConnection.objects.using("app_runtime")
            .filter(id=rows[1][2].id)
            .update(status="connected")
            == 0
        )


def test_foreign_tenant_context_does_not_expose_other_owner(rows):
    with identity_transaction(rows[0][0].id, using="app_runtime"):
        activate_tenant(rows[1][1].id, using="app_runtime")
        assert not QuickBooksConnection.objects.using("app_runtime").exists()
        assert not QuickBooksAttempt.objects.using("app_runtime").exists()
        assert not QuickBooksEvent.objects.using("app_runtime").exists()


def test_lost_owner_role_removes_credential_access(rows):
    user, org, *_ = rows[0]
    OrganizationMember.objects.filter(user=user, organization=org).update(role="viewer")
    with identity_transaction(user.id, using="app_runtime"):
        activate_tenant(org.id, using="app_runtime")
        assert not QuickBooksConnection.objects.using("app_runtime").exists()


def test_runtime_can_insert_and_lock_own_connection(rows):
    user, org, obj, *_ = rows[0]
    with identity_transaction(user.id, using="app_runtime"):
        activate_tenant(org.id, using="app_runtime")
        found = (
            QuickBooksConnection.objects.using("app_runtime")
            .select_for_update()
            .get(id=obj.id)
        )
        found.status = "connected"
        found.save(using="app_runtime")
        QuickBooksEvent.objects.using("app_runtime").create(
            connection_id=obj.id, kind="connected"
        )
    obj.refresh_from_db()
    assert obj.status == "connected"


def test_cross_tenant_insert_denied(rows):
    with pytest.raises(DatabaseError):
        with identity_transaction(rows[0][0].id, using="app_runtime"):
            activate_tenant(rows[0][1].id, using="app_runtime")
            QuickBooksAttempt.objects.using("app_runtime").create(
                connection_id=rows[1][2].id,
                state_hash="c" * 64,
                session_hash="b" * 64,
                generation=0,
                expires_at=timezone.now(),
            )


def test_event_history_cannot_be_rewritten(rows):
    with pytest.raises(DatabaseError):
        with identity_transaction(rows[0][0].id, using="app_runtime"):
            activate_tenant(rows[0][1].id, using="app_runtime")
            QuickBooksEvent.objects.using("app_runtime").filter(
                id=rows[0][4].id
            ).update(kind="forged")


@pytest.mark.parametrize(
    "model", [QuickBooksConnection, QuickBooksAttempt, QuickBooksEvent]
)
def test_worker_cannot_access_oauth_credentials_or_receipts(rows, model):
    with pytest.raises(DatabaseError):
        with tenant_transaction(rows[0][1].id, using="worker_runtime"):
            list(model.objects.using("worker_runtime").all())


def test_runtime_cannot_rebind_connection_identity(rows):
    user, org, obj, *_ = rows[0]
    second = Organization.objects.create(name="Same owner second workspace")
    OrganizationMember.objects.create(user=user, organization=second, role="owner")
    with pytest.raises(DatabaseError):
        with identity_transaction(user.id, using="app_runtime"):
            activate_tenant(org.id, using="app_runtime")
            QuickBooksConnection.objects.using("app_runtime").filter(id=obj.id).update(
                organization_id=second.id
            )
