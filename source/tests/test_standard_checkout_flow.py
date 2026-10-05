"""Actual-role frozen requests; SDK service calls are deliberate local mocks."""

import copy
from types import SimpleNamespace

import pytest
import stripe
from django.contrib.auth import get_user_model
from django.db import transaction

from apps.billing import standard_checkout_flow as flow
from apps.billing.models import (
    BillingCustomer,
    BillingCustomerRequest,
    CheckoutIntent,
    PaidCoverageAuthority,
)

pytestmark = pytest.mark.django_db(transaction=True, databases="__all__")
SUCCESS = "https://stewardence.example.invalid/billing/success/"
CANCEL = "https://stewardence.example.invalid/billing/cancel/"


@pytest.fixture
def setup(settings, monkeypatch):
    settings.STANDARD_CHECKOUT_INTENTS_ENABLED = True
    settings.STANDARD_CHECKOUT_STRIPE_KEY = "rk_test_example"
    user = get_user_model().objects.create_user(email="flow@example.invalid")
    PaidCoverageAuthority.objects.create(
        stripe_account_id="acct_flow",
        livemode=False,
        contracts={
            "standard": {
                "price_id": "price_core",
                "amount_cents": 9900,
                "contract_version": "core.monthly.v1",
            }
        },
    )
    calls = {"customer": [], "session": [], "retrieve": []}
    data = {}
    errors = {}
    mutations = {}

    def customer_create(*, params, options):
        calls["customer"].append((copy.deepcopy(params), copy.deepcopy(options)))
        data["customer"] = {
            "id": "cus_flow",
            "livemode": False,
            **copy.deepcopy(params),
        }
        if errors.pop("customer", False):
            raise stripe.APIConnectionError("Synthetic lost response")
        return {**data["customer"], **mutations.get("customer", {})}

    def session_create(*, params, options):
        calls["session"].append((copy.deepcopy(params), copy.deepcopy(options)))
        data["session"] = {
            "id": "cs_flow",
            "livemode": False,
            "customer": params["customer"],
            "client_reference_id": params["client_reference_id"],
            "metadata": params["metadata"],
            "expires_at": params["expires_at"],
            "mode": "subscription",
            "status": "open",
            "url": "https://checkout.stripe.com/c/pay/qualification",
        }
        if errors.pop("session", False):
            raise stripe.APIConnectionError("Synthetic lost response")
        return {**data["session"], **mutations.get("session", {})}

    def retrieve(session_id):
        calls["retrieve"].append(session_id)
        return {**data["session"], **mutations.get("session", {})}

    client = SimpleNamespace(
        v1=SimpleNamespace(
            accounts=SimpleNamespace(
                retrieve_current=lambda: {"id": mutations.get("account", "acct_flow")}
            ),
            prices=SimpleNamespace(
                retrieve=lambda price: {
                    "id": price,
                    "livemode": False,
                    "active": True,
                    "currency": "usd",
                    "unit_amount": 9900,
                    "recurring": {
                        "interval": "month",
                        "interval_count": 1,
                        "usage_type": "licensed",
                    },
                }
            ),
            customers=SimpleNamespace(
                create=customer_create, retrieve=lambda customer: data["customer"]
            ),
            checkout=SimpleNamespace(
                sessions=SimpleNamespace(create=session_create, retrieve=retrieve)
            ),
        )
    )
    monkeypatch.setattr(flow, "_client", lambda key: client)
    return user, calls, errors, mutations


def start(setup):
    return flow.start_standard_checkout(setup[0], SUCCESS, CANCEL, using="app_runtime")


def test_flag_closed_has_zero_provider_writes(setup, settings):
    settings.STANDARD_CHECKOUT_INTENTS_ENABLED = False
    with pytest.raises(flow.StandardCheckoutHold):
        start(setup)
    assert not setup[1]["customer"] and not setup[1]["session"]
    assert not BillingCustomerRequest.objects.exists()


def test_success_retry_retrieves_exact_observation_without_new_create(setup):
    first = start(setup)
    assert start(setup) == first
    assert len(setup[1]["customer"]) == len(setup[1]["session"]) == 1
    assert setup[1]["retrieve"] == ["cs_flow"]
    assert BillingCustomerRequest.objects.count() == CheckoutIntent.objects.count() == 1


@pytest.mark.parametrize("stage", ["customer", "session"])
def test_lost_response_retains_identical_body_and_key(setup, stage):
    setup[2][stage] = True
    with pytest.raises(flow.StandardCheckoutHold, match="ambiguous"):
        start(setup)
    assert BillingCustomerRequest.objects.count() == 1
    if stage == "session":
        assert CheckoutIntent.objects.count() == 1
    setup[0].email = "changed-after-timeout@example.invalid"
    assert start(setup).startswith("https://checkout.stripe.com/")
    assert setup[1][stage][0] == setup[1][stage][1]


@pytest.mark.parametrize(
    "mismatch",
    [
        {"customer": "cus_other"},
        {"livemode": True},
        {"metadata": {}},
        {"client_reference_id": "another-owner"},
        {"expires_at": True},
        {"mode": "payment"},
        {"url": "https://attacker.invalid/"},
    ],
)
def test_bad_checkout_response_cannot_record_observation(setup, mismatch):
    setup[3]["session"] = mismatch
    with pytest.raises(flow.StandardCheckoutHold):
        start(setup)
    intent = CheckoutIntent.objects.get()
    assert intent.observed_session_id is None and intent.state == "pending"


def test_account_mismatch_has_no_external_writes(setup):
    setup[3]["account"] = "acct_other"
    with pytest.raises(flow.StandardCheckoutHold):
        start(setup)
    assert not setup[1]["customer"] and not setup[1]["session"]


def test_mismatched_customer_never_binds_local_identity(setup):
    setup[3]["customer"] = {"metadata": {}}
    with pytest.raises(flow.StandardCheckoutHold):
        start(setup)
    assert BillingCustomer.objects.get().stripe_customer_id is None
    assert BillingCustomerRequest.objects.count() == 1
    assert not CheckoutIntent.objects.exists()


def test_outer_transaction_refused_before_writes(setup):
    with (
        transaction.atomic(using="app_runtime"),
        pytest.raises(flow.StandardCheckoutHold, match="independent"),
    ):
        start(setup)
    assert not setup[1]["customer"] and not setup[1]["session"]


def test_eight_concurrent_flows_never_create_different_request_bodies_or_keys(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    barrier = Barrier(8)

    def call():
        try:
            barrier.wait(timeout=10)
            try:
                return start(setup)
            except flow.CheckoutFlowHeld:
                return None
        finally:
            connections["app_runtime"].close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = [
            future.result(timeout=30)
            for future in [pool.submit(call) for _ in range(8)]
        ]
    assert any(value is not None for value in results)
    assert {value for value in results if value is not None} == {
        "https://checkout.stripe.com/c/pay/qualification"
    }
    assert BillingCustomerRequest.objects.count() == CheckoutIntent.objects.count() == 1
    for stage in ("customer", "session"):
        assert setup[1][stage]
        assert all(call == setup[1][stage][0] for call in setup[1][stage])
