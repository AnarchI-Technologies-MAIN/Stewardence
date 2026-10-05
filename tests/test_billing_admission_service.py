"""Original-signature ingester and exact effects on one real admission login."""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.db import connections, DatabaseError, transaction
from django.test import RequestFactory

from apps.billing.admission_views import paid_webhook
from apps.billing.models import (
    BillingCustomer,
    PaidCoverage,
    PaidCoverageAuthority,
    Subscription,
)
from tests.test_paid_evidence_contracts import paid_observations

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")


@contextmanager
def dedicated_default():
    original = connections["default"]
    dedicated = connections["billing_admission"]
    connections["default"] = dedicated
    try:
        yield
    finally:
        dedicated.close()
        connections["default"] = original


@pytest.fixture
def service(settings, monkeypatch, paid_observations):
    settings.BILLING_ADMISSION_WEBHOOK_SECRET = "whsec_synthetic_qualification"
    settings.BILLING_ADMISSION_STRIPE_KEY = "rk_test_synthetic_qualification"
    settings.BILLING_ADMISSION_ACCOUNT_ID = "acct_qualified"
    settings.BILLING_ADMISSION_LIVEMODE = False
    invoice, provider_subscription = paid_observations
    user = get_user_model().objects.create_user(
        email="admission-service@example.invalid"
    )
    customer = BillingCustomer.objects.create(
        user=user, stripe_customer_id="cus_qualified"
    )
    provider_subscription.update(
        status="active",
        metadata={"portfolio": "core", "stewardence_user_id": str(user.id)},
    )
    PaidCoverageAuthority.objects.create(
        stripe_account_id="acct_qualified",
        livemode=False,
        contracts={
            "standard": {
                "price_id": "price_core_99",
                "amount_cents": 9900,
                "contract_version": "core.monthly.v1",
            }
        },
    )
    account_read = Mock(return_value={"id": "acct_qualified"})
    invoice_read = Mock(return_value=invoice)
    subscription_read = Mock(return_value=provider_subscription)
    sdk = SimpleNamespace(
        v1=SimpleNamespace(
            accounts=SimpleNamespace(retrieve_current=account_read),
            invoices=SimpleNamespace(retrieve=invoice_read),
            subscriptions=SimpleNamespace(retrieve=subscription_read),
        )
    )
    client = Mock(return_value=sdk)
    monkeypatch.setattr("apps.billing.admission.stripe.StripeClient", client)
    return customer, invoice, provider_subscription, client, account_read


def delivery(
    settings,
    *,
    event_id="evt_ingester",
    invoice_id="in_qualified",
    mode=False,
    changes=None,
    secret=None,
):
    event = {
        "id": event_id,
        "object": "event",
        "type": "invoice.paid",
        "livemode": mode,
        "data": {"object": {"id": invoice_id, "object": "invoice"}},
    }
    event.update(changes or {})
    raw = json.dumps(event, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signing = (
        secret if secret is not None else settings.BILLING_ADMISSION_WEBHOOK_SECRET
    )
    signature = hmac.new(
        signing.encode(), str(timestamp).encode() + b"." + raw, hashlib.sha256
    ).hexdigest()
    return RequestFactory().post(
        "/billing/paid-webhook/",
        raw,
        content_type="application/json",
        HTTP_STRIPE_SIGNATURE=f"t={timestamp},v1={signature}",
    )


def count_receipts():
    with connections["default"].cursor() as cursor:
        cursor.execute("SELECT count(*) FROM billing_admission_receipt")
        return cursor.fetchone()[0]


def test_original_signed_invoice_creates_standard_generation_and_atomic_receipt(
    service, settings
):
    customer, _, _, client, account = service
    with dedicated_default():
        response = paid_webhook(delivery(settings))
        duplicate = paid_webhook(delivery(settings))
    assert response.status_code == duplicate.status_code == 200
    subscription = Subscription.objects.get(billing_customer=customer)
    assert subscription.status == "active" and not subscription.is_founder
    assert subscription.stripe_subscription_id == "sub_qualified"
    assert PaidCoverage.objects.count() == count_receipts() == 1
    assert account.call_count == 1
    assert client.call_args.args == ("rk_test_synthetic_qualification",)


@pytest.mark.parametrize("secret", ["", "whsec_", "  ", "wrong"])
def test_bad_service_secret_fails_before_signature_or_provider(
    service, settings, secret
):
    req = delivery(settings)
    settings.BILLING_ADMISSION_WEBHOOK_SECRET = secret
    with dedicated_default():
        assert paid_webhook(req).status_code == 503
    service[3].assert_not_called()
    assert not Subscription.objects.exists()


def test_forged_signature_and_wrong_role_never_call_provider(service, settings):
    with dedicated_default():
        assert (
            paid_webhook(delivery(settings, secret="whsec_forged")).status_code == 400
        )
    # Normal default is owner qualification connection, not the service role.
    assert paid_webhook(delivery(settings)).status_code == 503
    service[3].assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [{"livemode": True}, {"account": "acct_other"}, {"type": "customer.updated"}],
)
def test_unadmitted_event_environment_account_and_type(service, settings, changes):
    with dedicated_default():
        assert paid_webhook(delivery(settings, changes=changes)).status_code == 422
    service[3].assert_not_called()
    assert count_receipts() == 0


def test_invalid_coverage_rolls_back_new_generation_and_receipt(service, settings):
    service[1]["amount_remaining"] = 1
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 422
    assert not Subscription.objects.exists()
    assert not PaidCoverage.objects.exists()
    assert count_receipts() == 0


def test_same_event_conflicting_body_does_not_commit_new_effect(service, settings):
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 200
        assert (
            paid_webhook(
                delivery(settings, changes={"metadata": {"conflicting": "body"}})
            ).status_code
            == 503
        )
    assert PaidCoverage.objects.count() == count_receipts() == 1


def test_canceled_generation_remains_terminal(service, settings):
    customer = service[0]
    Subscription.objects.create(
        billing_customer=customer,
        portfolio="core",
        status="canceled",
        stripe_subscription_id="sub_qualified",
    )
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 503
    assert Subscription.objects.get(billing_customer=customer).status == "canceled"
    assert not PaidCoverage.objects.exists()
    assert count_receipts() == 0


def test_app_and_worker_cannot_execute_ingester_or_write_receipts(service):
    for alias in ("app_runtime", "worker_runtime"):
        with pytest.raises(DatabaseError), transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    "SELECT app_private.begin_paid_admission('cus_qualified','sub_qualified','acct_qualified',false,'no-owner','core','standard')"
                )
    with connections["billing_admission"].cursor() as cursor:
        cursor.execute(
            "SELECT current_user,has_table_privilege(current_user,'billing_subscription','UPDATE'),has_table_privilege(current_user,'billing_admission_receipt','INSERT')"
        )
        assert cursor.fetchone() == ("agentledger_billing_admission", False, False)


def test_missing_database_authority_stops_before_account_access(service, settings):
    PaidCoverageAuthority.objects.all().delete()
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 503
    service[3].assert_not_called()
    assert not Subscription.objects.exists()


def test_provider_network_failure_commits_no_receipt(service, settings):
    import stripe

    service[4].side_effect = stripe.APIConnectionError(
        "Synthetic connection uncertainty"
    )
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 503
    assert not Subscription.objects.exists()
    assert not PaidCoverage.objects.exists()
    assert count_receipts() == 0


def test_paid_historical_interval_does_not_activate_new_subscription(service, settings):
    now = int(time.time())
    service[1]["lines"]["data"][0]["period"] = {"start": now - 3600, "end": now - 600}
    service[1]["status_transitions"]["paid_at"] = now - 3000
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 200
    assert Subscription.objects.get(billing_customer=service[0]).status == "pending"
    assert PaidCoverage.objects.count() == count_receipts() == 1


def test_existing_canceling_state_is_preserved_by_paid_receipt(service, settings):
    Subscription.objects.create(
        billing_customer=service[0],
        portfolio="core",
        status="canceling",
        stripe_subscription_id="sub_qualified",
        cancel_at_period_end=True,
    )
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 200
    subscription = Subscription.objects.get(billing_customer=service[0])
    assert subscription.status == "canceling" and subscription.cancel_at_period_end
    assert PaidCoverage.objects.count() == count_receipts() == 1


def test_distinct_event_delivery_same_invoice_records_one_coverage(service, settings):
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 200
        assert (
            paid_webhook(delivery(settings, event_id="evt_second_delivery")).status_code
            == 200
        )
    assert PaidCoverage.objects.count() == 1
    assert count_receipts() == 2


def test_historical_founder_intro_arrival_cannot_overwrite_ongoing_price(
    service, settings
):
    from datetime import datetime, UTC

    customer, invoice, provider_subscription, _, _ = service
    now = int(time.time())
    boundary = now - 86400
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = "price_core_intro"
    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = "price_core_ongoing"
    authority = PaidCoverageAuthority.objects.get()
    authority.contracts.update(
        {
            phase: {
                "price_id": price,
                "amount_cents": amount,
                "contract_version": "core.monthly.v1",
            }
            for phase, price, amount in (
                ("founder_intro", "price_core_intro", 4900),
                ("founder_ongoing", "price_core_ongoing", 7500),
            )
        }
    )
    authority.save()
    subscription = Subscription.objects.create(
        billing_customer=customer,
        portfolio="core",
        status="active",
        stripe_subscription_id="sub_qualified",
        is_founder=True,
        founder_sequence=1,
        founder_intro_ends_at=datetime.fromtimestamp(boundary, UTC),
        current_price_cents=4900,
    )

    def observations(invoice_id, price_id, amount, start, end):
        invoice["id"] = invoice_id
        invoice["amount_due"] = invoice["amount_paid"] = amount
        invoice["status_transitions"]["paid_at"] = start + 10
        line = invoice["lines"]["data"][0]
        line["amount"] = amount
        line["period"] = {"start": start, "end": end}
        line["pricing"]["price_details"]["price"] = price_id
        provider_subscription["items"]["data"][0]["price"].update(
            id=price_id, unit_amount=amount
        )

    observations("in_ongoing", "price_core_ongoing", 7500, now - 60, now + 30 * 86400)
    with dedicated_default():
        assert (
            paid_webhook(
                delivery(settings, event_id="evt_ongoing", invoice_id="in_ongoing")
            ).status_code
            == 200
        )
    subscription.refresh_from_db()
    ongoing_end = subscription.current_period_end
    assert subscription.current_price_cents == 7500
    observations(
        "in_intro_history", "price_core_intro", 4900, now - 31 * 86400, boundary
    )
    with dedicated_default():
        assert (
            paid_webhook(
                delivery(
                    settings,
                    event_id="evt_intro_history",
                    invoice_id="in_intro_history",
                )
            ).status_code
            == 200
        )
    subscription.refresh_from_db()
    assert subscription.current_price_cents == 7500
    assert subscription.current_period_end == ongoing_end
    assert subscription.is_founder and subscription.status == "active"
    assert PaidCoverage.objects.count() == count_receipts() == 2


def test_same_service_boundary_different_price_contract_requires_review(
    service, settings
):
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 200
    subscription = Subscription.objects.get(billing_customer=service[0])
    before = Subscription.objects.filter(pk=subscription.pk).values().get()
    authority = PaidCoverageAuthority.objects.get()
    authority.contracts["standard"]["price_id"] = "price_core_revised"
    authority.save()
    settings.STRIPE_CORE_STANDARD_PRICE_ID = "price_core_revised"
    service[1]["id"] = "in_revised_contract"
    service[1]["lines"]["data"][0]["pricing"]["price_details"]["price"] = (
        "price_core_revised"
    )
    service[2]["items"]["data"][0]["price"]["id"] = "price_core_revised"
    with dedicated_default():
        assert (
            paid_webhook(
                delivery(
                    settings,
                    event_id="evt_revised_contract",
                    invoice_id="in_revised_contract",
                )
            ).status_code
            == 503
        )
    assert Subscription.objects.filter(pk=subscription.pk).values().get() == before
    assert PaidCoverage.objects.count() == count_receipts() == 1


@pytest.mark.parametrize("cancel_generation", [False, True])
def test_exact_committed_replay_acknowledges_without_provider_or_projection(
    service, settings, cancel_generation
):
    import stripe

    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 200
    subscription = Subscription.objects.get(billing_customer=service[0])
    if cancel_generation:
        subscription.status = "canceled"
        subscription.save(update_fields=["status"])
    before = Subscription.objects.filter(pk=subscription.pk).values().get()
    service[3].side_effect = stripe.APIConnectionError(
        "Synthetic provider outage after commit"
    )
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 200
    assert service[3].call_count == 1
    assert Subscription.objects.filter(pk=subscription.pk).values().get() == before
    assert PaidCoverage.objects.count() == count_receipts() == 1


def test_committed_lookup_is_admission_only_and_binds_raw_body_account_mode(
    service, settings
):
    req = delivery(settings)
    body_hash = hashlib.sha256(req.body).hexdigest()
    with dedicated_default():
        assert paid_webhook(req).status_code == 200
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT app_private.committed_paid_admission(%s,false,%s,'invoice.paid',%s)",
                ["acct_qualified", "evt_ingester", body_hash],
            )
            coverage = cursor.fetchone()[0]
    assert coverage == PaidCoverage.objects.get().id
    for alias in ("app_runtime", "worker_runtime"):
        with pytest.raises(DatabaseError), transaction.atomic(using=alias):
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    "SELECT app_private.committed_paid_admission(%s,false,%s,'invoice.paid',%s)",
                    ["acct_qualified", "evt_ingester", body_hash],
                )
    for account, mode, digest in (
        ("acct_other", False, body_hash),
        ("acct_qualified", True, body_hash),
        ("acct_qualified", False, "f" * 64),
    ):
        with (
            pytest.raises(DatabaseError),
            transaction.atomic(using="billing_admission"),
        ):
            with connections["billing_admission"].cursor() as cursor:
                cursor.execute(
                    "SELECT app_private.committed_paid_admission(%s,%s,%s,'invoice.paid',%s)",
                    [account, mode, "evt_ingester", digest],
                )
    assert PaidCoverage.objects.count() == count_receipts() == 1


@pytest.mark.parametrize("authority_change", ["removed", "price_changed"])
def test_exact_replay_survives_issuance_config_change_without_new_effect(
    service, settings, authority_change
):
    import stripe

    request = delivery(settings)
    with dedicated_default():
        assert paid_webhook(request).status_code == 200
    before = Subscription.objects.values().get()
    coverage_id = PaidCoverage.objects.get().id
    if authority_change == "removed":
        PaidCoverageAuthority.objects.all().delete()
    if authority_change == "price_changed":
        authority = PaidCoverageAuthority.objects.get()
        authority.contracts["standard"]["price_id"] = "price_reconfigured"
        authority.save()
        settings.STRIPE_CORE_STANDARD_PRICE_ID = "price_reconfigured"
    service[3].side_effect = stripe.APIConnectionError("Synthetic provider outage")
    with dedicated_default():
        assert paid_webhook(delivery(settings)).status_code == 200
        assert service[3].call_count == 1
        # A distinct event still has to qualify as a new effect.
        assert (
            paid_webhook(
                delivery(settings, event_id="evt_new_after_change")
            ).status_code
            != 200
        )
    assert Subscription.objects.values().get() == before
    assert PaidCoverage.objects.get().id == coverage_id
    assert count_receipts() == 1
