import os

import pytest
from django.db import DatabaseError, connections, transaction

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.accounts.models import User
from apps.billing.models import BillingCustomer, FounderSlot, Subscription
from apps.organizations.models import Organization, OrganizationMember

pytestmark = [
    pytest.mark.rls,
    pytest.mark.skipif(
        os.getenv("AGENTLEDGER_RLS_TESTS") != "1",
        reason="restricted-role harness required",
    ),
    pytest.mark.django_db(
        transaction=True, databases={"default", "app_runtime", "worker_runtime"}
    ),
]


@pytest.fixture
def accounts():
    result = []
    for index in range(2):
        user = User.objects.create_user(
            f"billing-rls-{index}@example.com", "Test!BillingAuth123"
        )
        org = Organization.objects.create(name=f"Billing RLS {index}")
        OrganizationMember.objects.create(user=user, organization=org, role="owner")
        customer = BillingCustomer.objects.create(user=user)
        sub = Subscription.objects.create(
            billing_customer=customer,
            organization=org,
            stripe_subscription_id=f"sub_rls_{index}",
            status="active",
        )
        FounderSlot.objects.create(sequence=index + 1, billing_customer=customer)
        result.append((user, org, customer, sub))
    FounderSlot.objects.create(sequence=3)
    return result


def test_customer_subscription_and_founder_tokens_are_private(accounts):
    user, _, customer, sub = accounts[0]
    with identity_transaction(user.id, using="app_runtime"):
        assert list(
            BillingCustomer.objects.using("app_runtime").values_list("id", flat=True)
        ) == [customer.id]
        assert list(
            Subscription.objects.using("app_runtime").values_list("id", flat=True)
        ) == [sub.id]
        assert set(
            FounderSlot.objects.using("app_runtime").values_list("sequence", flat=True)
        ) == {1, 3}
        assert (
            Subscription.objects.using("app_runtime")
            .filter(id=accounts[1][3].id)
            .update(status="canceled")
            == 0
        )


def test_no_identity_exposes_no_customer(accounts):
    assert not BillingCustomer.objects.using("app_runtime").exists()
    assert not Subscription.objects.using("app_runtime").exists()


def test_customer_cannot_bind_subscription_to_foreign_workspace(accounts):
    with pytest.raises(DatabaseError):
        with identity_transaction(accounts[0][0].id, using="app_runtime"):
            Subscription.objects.using("app_runtime").filter(
                id=accounts[0][3].id
            ).update(organization_id=accounts[1][1].id)


def test_foreign_slot_cannot_be_stolen(accounts):
    user, _, customer, _ = accounts[0]
    with identity_transaction(user.id, using="app_runtime"):
        assert (
            FounderSlot.objects.using("app_runtime")
            .filter(sequence=2)
            .update(billing_customer_id=customer.id)
            == 0
        )
    with pytest.raises(DatabaseError):
        with identity_transaction(user.id, using="app_runtime"):
            FounderSlot.objects.using("app_runtime").filter(sequence=3).update(
                billing_customer_id=accounts[1][2].id
            )


def test_worker_reads_only_current_workspaces_entitlement(accounts):
    with tenant_transaction(accounts[0][1].id, using="worker_runtime"):
        assert list(
            Subscription.objects.using("worker_runtime").values_list("id", flat=True)
        ) == [accounts[0][3].id]
    with pytest.raises(DatabaseError):
        with transaction.atomic(using="worker_runtime"):
            Subscription.objects.using("worker_runtime").update(status="active")


def test_exact_event_lookup(accounts):
    with connections["app_runtime"].cursor() as cursor:
        cursor.execute(
            "SELECT app_private.billing_event_user(%s, false)", ["sub_rls_1"]
        )
        assert cursor.fetchone()[0] == accounts[1][0].id
        cursor.execute(
            "SELECT app_private.billing_event_user(%s, false)", ["sub_missing"]
        )
        assert cursor.fetchone()[0] is None
