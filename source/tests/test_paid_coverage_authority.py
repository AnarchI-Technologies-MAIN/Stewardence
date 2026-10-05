"""Synthetic admitted evidence under actual isolated PostgreSQL login roles."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from django.db import DatabaseError, connections, transaction
from django.utils import timezone

from agentledger.tenancy.context import identity_transaction, tenant_transaction
from apps.billing.entitlements import issue_paid_coverage, paid_subscription_access, paid_subscription_export_access
from apps.billing.models import PaidCoverage, PaidCoverageAuthority, Subscription
from apps.organizations.models import Organization, OrganizationMember
from tests.test_billing_portal_cancellation import make_subscription

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@pytest.fixture
def admitted():
    assert connections["default"].vendor == "postgresql"
    user, customer, subscription = make_subscription(
        email="paid-authority@example.invalid", founder=False, issued_coverage=False
    )
    org = Organization.objects.create(name="Synthetic paid authority")
    OrganizationMember.objects.create(organization=org, user=user, role="owner")
    subscription.organization = org
    subscription.save(update_fields=["organization"])
    PaidCoverageAuthority.objects.create(stripe_account_id="acct_qualification", livemode=False,
        contracts={"standard": {"price_id": "price_core_standard", "amount_cents": 9900, "contract_version": "core.monthly.v1"}})
    now = int(timezone.now().timestamp())
    evidence = {"schema": "stewardence.paid_coverage.v1", "subscription_id": str(subscription.id),
        "stripe_subscription_id": "sub_test", "stripe_customer_id": customer.stripe_customer_id,
        "stripe_account_id": "acct_qualification", "livemode": False,
        "stripe_invoice_id": "in_qualification", "stripe_event_id": "evt_qualification",
        "contract_version": "core.monthly.v1", "phase": "standard", "stripe_price_id": "price_core_standard",
        "amount_cents": 9900, "currency": "usd", "service_start": now-3600,
        "service_end": now+3600, "paid_at": now-3500, "evidence_sha256": "a"*64}
    return user, org, subscription, evidence


def test_issuer_is_actual_separate_login_and_app_worker_cannot_issue(admitted):
    user, org, subscription, evidence = admitted
    with connections["billing_admission"].cursor() as cursor:
        cursor.execute("SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user")
        assert cursor.fetchone() == ("agentledger_billing_admission", False, False)
    for alias in ("app_runtime", "worker_runtime"):
        with pytest.raises(DatabaseError), transaction.atomic(using=alias):
            issue_paid_coverage(evidence, using=alias)
    receipt = issue_paid_coverage(evidence)
    with identity_transaction(user.id, using="app_runtime"):
        assert paid_subscription_access(subscription.id, using="app_runtime")
        assert PaidCoverage.objects.using("app_runtime").get(pk=receipt).stripe_invoice_id == "in_qualification"
    with tenant_transaction(org.id, using="worker_runtime"):
        assert paid_subscription_access(subscription.id, using="worker_runtime")


@pytest.mark.parametrize("field,value", [
    ("livemode", True), ("stripe_account_id", "acct_wrong"), ("stripe_customer_id", "cus_wrong"),
    ("stripe_subscription_id", "sub_wrong"), ("stripe_price_id", "price_unregistered"),
    ("amount_cents", True), ("amount_cents", 9900.0), ("amount_cents", 9800),
    ("currency", "eur"), ("phase", "founder_intro"), ("service_start", True),
    ("contract_version", "unknown"), ("stripe_event_id", "not_an_event"),
])
def test_issuer_rejects_unadmitted_identity_and_contract(admitted, field, value):
    _, _, _, evidence = admitted
    with pytest.raises(DatabaseError), transaction.atomic(using="billing_admission"):
        issue_paid_coverage({**evidence, field: value})
    assert not PaidCoverage.objects.exists()


def test_observed_future_period_is_not_payment_and_expired_receipt_is_not_access(admitted):
    user, _, subscription, evidence = admitted
    subscription.current_period_end = timezone.now() + timezone.timedelta(days=100)
    subscription.save(update_fields=["current_period_end"])
    with identity_transaction(user.id, using="app_runtime"):
        assert not paid_subscription_access(subscription.id, using="app_runtime")
    now = int(timezone.now().timestamp())
    issue_paid_coverage({**evidence, "service_start": now-7200, "service_end": now-3600, "paid_at": now-7100})
    with identity_transaction(user.id, using="app_runtime"):
        assert not paid_subscription_access(subscription.id, using="app_runtime")


def test_missing_pin_denies_issuance(admitted):
    _, _, _, evidence = admitted
    PaidCoverageAuthority.objects.all().delete()
    with pytest.raises(DatabaseError), transaction.atomic(using="billing_admission"):
        issue_paid_coverage(evidence)
    assert not PaidCoverage.objects.exists()


def test_invoice_replay_is_exact_and_append_only(admitted):
    _, _, _, evidence = admitted
    receipt = issue_paid_coverage(evidence)
    assert issue_paid_coverage({**evidence, "stripe_event_id": "evt_other_delivery"}) == receipt
    with pytest.raises(DatabaseError), transaction.atomic(using="billing_admission"):
        issue_paid_coverage({**evidence, "evidence_sha256": "b"*64})
    assert PaidCoverage.objects.count() == 1
    with pytest.raises(DatabaseError), transaction.atomic():
        PaidCoverage.objects.filter(pk=receipt).update(service_end=timezone.now())
    with pytest.raises(DatabaseError), transaction.atomic():
        PaidCoverage.objects.filter(pk=receipt).delete()


def test_admission_role_has_no_raw_payment_or_provider_or_tenant_writes(admitted):
    _, _, subscription, evidence = admitted
    with pytest.raises(DatabaseError), transaction.atomic(using="billing_admission"):
        Subscription.objects.using("billing_admission").filter(pk=subscription.id).update(status="active")
    with connections["billing_admission"].cursor() as cursor:
        cursor.execute("SELECT has_table_privilege(current_user,'billing_paid_coverage','INSERT'),"
            "has_table_privilege(current_user,'organizations_organization','UPDATE')")
        assert cursor.fetchone() == (False, False)
    with pytest.raises(RuntimeError), transaction.atomic(using="billing_admission"):
        issue_paid_coverage(evidence)
        raise RuntimeError("Synthetic transaction interruption")
    assert not PaidCoverage.objects.exists()


def test_generation_replacement_and_terminal_status_cannot_inherit_access(admitted):
    user, _, subscription, evidence = admitted
    issue_paid_coverage(evidence)
    for changes in ({"stripe_subscription_id": "sub_replacement"}, {"status": "canceled"}):
        Subscription.objects.filter(pk=subscription.pk).update(**changes)
        with identity_transaction(user.id, using="app_runtime"):
            assert not paid_subscription_access(subscription.id, using="app_runtime")
        Subscription.objects.filter(pk=subscription.pk).update(stripe_subscription_id="sub_test", status="active")


def test_simultaneous_same_invoice_issuance_converges(admitted):
    _, _, _, evidence = admitted
    barrier = Barrier(4)
    def admit():
        try:
            barrier.wait(timeout=10)
            return issue_paid_coverage(evidence)
        finally:
            connections["billing_admission"].close()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(admit) for _ in range(4)]
        receipts = [future.result(timeout=20) for future in futures]
    assert len(set(receipts)) == 1
    assert PaidCoverage.objects.count() == 1


def test_other_tenant_cannot_read_or_claim_receipt(admitted):
    _, _, subscription, evidence = admitted
    issue_paid_coverage(evidence)
    from django.contrib.auth import get_user_model
    other = get_user_model().objects.create_user(email=f"{uuid4()}@other.example.invalid")
    with identity_transaction(other.id, using="app_runtime"):
        assert not paid_subscription_access(subscription.id, using="app_runtime")
        assert not PaidCoverage.objects.using("app_runtime").exists()


@pytest.mark.parametrize("days_since_expiry,allowed", [(1, True), (89, True), (91, False)])
def test_export_window_is_separate_from_paid_access(admitted, days_since_expiry, allowed):
    user, _, subscription, evidence = admitted
    end = int(timezone.now().timestamp())-days_since_expiry*86400
    issue_paid_coverage({**evidence, "service_start": end-86400, "service_end": end, "paid_at": end-86300})
    Subscription.objects.filter(pk=subscription.id).update(status="canceled", stripe_subscription_id="sub_new_generation")
    with identity_transaction(user.id, using="app_runtime"):
        assert not paid_subscription_access(subscription.id, using="app_runtime")
        assert paid_subscription_export_access(subscription.id, using="app_runtime") is allowed


def test_app_worker_raw_receipt_insertion_and_admission_role_table_access_denied(admitted):
    for alias in ("app_runtime", "worker_runtime", "billing_admission"):
        with pytest.raises(DatabaseError) as denied, transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute("INSERT INTO billing_paid_coverage DEFAULT VALUES")
        assert denied.value.__cause__.sqlstate == "42501"
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT proname,provolatile FROM pg_proc JOIN pg_namespace n ON n.oid=pronamespace"
            " WHERE n.nspname='app_private' AND proname IN ('paid_subscription_access','paid_subscription_export_access') ORDER BY proname")
        assert cursor.fetchall() == [("paid_subscription_access", "v"), ("paid_subscription_export_access", "v")]


@pytest.mark.parametrize("coverage_state,allowed", [("current", True), ("expired", False), ("missing", False)])
def test_failed_renewal_projection_does_not_override_issued_coverage(admitted, coverage_state, allowed):
    user, _, subscription, evidence = admitted
    if coverage_state == "current":
        issue_paid_coverage(evidence)
    if coverage_state == "expired":
        now = int(timezone.now().timestamp())
        issue_paid_coverage({**evidence, "service_start": now-7200, "service_end": now-3600, "paid_at": now-7100})
    Subscription.objects.filter(pk=subscription.id).update(status="past_due")
    with identity_transaction(user.id, using="app_runtime"):
        assert paid_subscription_access(subscription.id, using="app_runtime") is allowed


def test_admission_role_has_no_provider_table_access(admitted):
    from apps.integrations.models import ProviderConnection, QuickBooksConnection
    with connections["billing_admission"].cursor() as cursor:
        for model in (ProviderConnection, QuickBooksConnection):
            cursor.execute("SELECT has_table_privilege(current_user,%s,'SELECT'),"
                "has_table_privilege(current_user,%s,'INSERT'),has_table_privilege(current_user,%s,'UPDATE')",
                [model._meta.db_table]*3)
            assert cursor.fetchone() == (False, False, False)
