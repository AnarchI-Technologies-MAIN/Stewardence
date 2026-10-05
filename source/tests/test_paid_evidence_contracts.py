"""Invoice renewal admission is independent of latest Checkout/current period."""

from copy import deepcopy
from uuid import uuid4

import pytest
from django.utils import timezone

from apps.billing.paid_evidence import UnsupportedPaidEvidence, normalize_paid_invoice


@pytest.fixture
def paid_observations(settings):
    settings.STRIPE_CORE_STANDARD_PRICE_ID = "price_core_99"
    settings.STRIPE_CORE_FOUNDER_INTRO_PRICE_ID = ""
    settings.STRIPE_CORE_FOUNDER_ONGOING_PRICE_ID = ""
    now = int(timezone.now().timestamp())
    subscription = {
        "id": "sub_qualified",
        "customer": "cus_qualified",
        "livemode": False,
        "items": {
            "has_more": False,
            "data": [
                {
                    "id": "si_qualified",
                    "quantity": 1,
                    "price": {
                        "id": "price_core_99",
                        "active": True,
                        "currency": "usd",
                        "unit_amount": 9900,
                        "recurring": {
                            "interval": "month",
                            "interval_count": 1,
                            "usage_type": "licensed",
                        },
                    },
                }
            ],
        },
    }
    invoice = {
        "id": "in_qualified",
        "object": "invoice",
        "status": "paid",
        "customer": "cus_qualified",
        "livemode": False,
        "currency": "usd",
        "amount_due": 9900,
        "amount_paid": 9900,
        "amount_remaining": 0,
        "status_transitions": {"paid_at": now - 10},
        "parent": {
            "type": "subscription_details",
            "subscription_details": {"subscription": "sub_qualified"},
        },
        "lines": {
            "has_more": False,
            "data": [
                {
                    "amount": 9900,
                    "currency": "usd",
                    "quantity": 1,
                    "period": {"start": now - 60, "end": now + 30 * 86400},
                    "parent": {
                        "type": "subscription_item_details",
                        "subscription_item_details": {
                            "subscription": "sub_qualified",
                            "subscription_item": "si_qualified",
                            "proration": False,
                        },
                    },
                    "pricing": {
                        "type": "price_details",
                        "price_details": {"price": "price_core_99"},
                    },
                }
            ],
        },
    }
    return invoice, subscription


def normalize(observations, **overrides):
    options = {
        "subscription_id": uuid4(),
        "account_id": "acct_qualified",
        "livemode": False,
        "event_id": "evt_qualified",
    }
    options.update(overrides)
    return normalize_paid_invoice(*observations, **options)


def test_renewal_uses_exact_invoice_service_period_not_latest_observation(
    paid_observations,
):
    invoice, subscription = paid_observations
    subscription["latest_invoice"] = "in_another"
    subscription["current_period_end"] = 1
    result = normalize(paid_observations)
    assert result["service_end"] == invoice["lines"]["data"][0]["period"]["end"]
    assert result["stripe_invoice_id"] == "in_qualified"
    assert result["amount_cents"] == 9900


def test_invoice_digest_does_not_change_for_redelivery(paid_observations):
    first = normalize(paid_observations, event_id="evt_first")
    second = normalize(paid_observations, event_id="evt_second")
    assert first["evidence_sha256"] == second["evidence_sha256"]
    assert first["stripe_event_id"] != second["stripe_event_id"]


def test_historical_paid_invoice_can_record_history_not_fabricate_current_period(
    paid_observations,
):
    invoice, _ = paid_observations
    line = invoice["lines"]["data"][0]
    for key in ("start", "end"):
        line["period"][key] -= 60 * 86400
    invoice["status_transitions"]["paid_at"] -= 60 * 86400
    result = normalize(paid_observations)
    assert result["service_end"] < int(timezone.now().timestamp())


@pytest.mark.parametrize(
    "mutation",
    [
        "foreign_customer",
        "foreign_subscription",
        "foreign_item",
        "foreign_price",
        "wrong_mode",
        "unpaid",
        "partial",
        "extra_total",
        "truncated_lines",
        "multiple_lines",
        "boolean_money",
        "boolean_time",
        "proration",
        "future_payment",
        "payment_after_period",
        "missing_subscription_pagination",
        "missing_quantity",
        "malformed_items",
        "line_invoice",
        "line_object",
    ],
)
def test_unsupported_invoice_never_normalizes(paid_observations, mutation):
    invoice, subscription = deepcopy(paid_observations)
    line = invoice["lines"]["data"][0]
    details = line["parent"]["subscription_item_details"]
    if mutation == "foreign_customer":
        invoice["customer"] = "cus_other"
    if mutation == "foreign_subscription":
        details["subscription"] = "sub_other"
    if mutation == "foreign_item":
        details["subscription_item"] = "si_other"
    if mutation == "foreign_price":
        line["pricing"]["price_details"]["price"] = "price_other"
    if mutation == "wrong_mode":
        invoice["livemode"] = True
    if mutation == "unpaid":
        invoice["status"] = "open"
    if mutation == "partial":
        invoice["amount_paid"] = 4900
    if mutation == "extra_total":
        invoice["amount_due"] = 10000
    if mutation == "truncated_lines":
        invoice["lines"]["has_more"] = True
    if mutation == "multiple_lines":
        invoice["lines"]["data"].append(deepcopy(line))
    if mutation == "boolean_money":
        line["quantity"] = True
    if mutation == "boolean_time":
        line["period"]["start"] = True
    if mutation == "proration":
        details["proration"] = True
    if mutation == "future_payment":
        invoice["status_transitions"]["paid_at"] += 86400
    if mutation == "payment_after_period":
        invoice["status_transitions"]["paid_at"] = line["period"]["end"]
    if mutation == "missing_subscription_pagination":
        subscription["items"].pop("has_more")
    if mutation == "missing_quantity":
        subscription["items"]["data"][0].pop("quantity")
    if mutation == "malformed_items":
        subscription["items"] = []
    if mutation == "line_invoice":
        line["invoice"] = "in_other"
    if mutation == "line_object":
        line["object"] = None
    with pytest.raises((UnsupportedPaidEvidence, ValueError)):
        normalize((invoice, subscription))
