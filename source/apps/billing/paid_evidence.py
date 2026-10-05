"""Normalize an authenticated invoice observation, never authenticate payment.

Only the separately credentialed billing ingester may issue the resulting
envelope. A correct digest is not proof that an observation came from Stripe.
The supported renewal shape is deliberately narrower than arbitrary invoices.
"""

import hashlib

import rfc8785
from django.utils import timezone

from .pricing import subscription_price_contract, validate_price_object


class UnsupportedPaidEvidence(ValueError):
    """Evidence cannot issue the supported monthly Core contract."""


def _identity(value, prefix):
    if type(value) is not str or not value.startswith(prefix) or len(value) > 255:
        raise UnsupportedPaidEvidence("Invalid paid-evidence identity")
    if len(value) == len(prefix) or any(character.isspace() for character in value):
        raise UnsupportedPaidEvidence("Invalid paid-evidence identity")
    return value


def normalize_paid_invoice(
    invoice,
    authoritative_subscription,
    *,
    subscription_id,
    account_id,
    livemode,
    event_id,
):
    """Admit an exact retrieved invoice without inventing Checkout fields.

    Historical service intervals may be recorded, but cannot grant current access.
    Tax, discounts, credits, prorations and multiple lines require reconciliation.
    Caller authenticates the event/account and retrieves these exact observations.
    """
    if type(invoice) is not dict or type(authoritative_subscription) is not dict:
        raise UnsupportedPaidEvidence("Plain invoice and subscription required")
    if type(livemode) is not bool or invoice.get("livemode") is not livemode:
        raise UnsupportedPaidEvidence("Invoice environment does not match")
    items = authoritative_subscription.get("items", {})
    if (
        type(items) is not dict
        or items.get("has_more") is not False
        or type(items.get("data")) is not list
        or len(items["data"]) != 1
    ):
        raise UnsupportedPaidEvidence("Complete subscription items required")
    item = items["data"][0]
    if (
        type(item) is not dict
        or type(item.get("price")) is not dict
        or type(item.get("quantity")) is not int
        or item["quantity"] != 1
    ):
        raise UnsupportedPaidEvidence("Invalid subscription item")
    contract = subscription_price_contract(authoritative_subscription)
    if contract is None or contract.portfolio != "core":
        raise UnsupportedPaidEvidence("Registered Core price contract required")
    validate_price_object(item["price"], contract)
    customer = _identity(authoritative_subscription.get("customer"), "cus_")
    external_subscription = _identity(authoritative_subscription.get("id"), "sub_")
    invoice_id = _identity(invoice.get("id"), "in_")
    item_id = _identity(item.get("id"), "si_")
    price_id = _identity(item["price"].get("id"), "price_")
    if authoritative_subscription.get("livemode") is not livemode:
        raise UnsupportedPaidEvidence("Subscription environment does not match")
    parent = invoice.get("parent")
    lines = invoice.get("lines")
    transitions = invoice.get("status_transitions")
    if any(type(value) is not dict for value in (parent, lines, transitions)):
        raise UnsupportedPaidEvidence("Complete invoice evidence required")
    details = parent.get("subscription_details")
    data = lines.get("data")
    if (
        parent.get("type") != "subscription_details"
        or type(details) is not dict
        or details.get("subscription") != external_subscription
        or type(data) is not list
        or len(data) != 1
        or lines.get("has_more") is not False
    ):
        raise UnsupportedPaidEvidence("One complete bound invoice line required")
    line = data[0]
    if type(line) is not dict:
        raise UnsupportedPaidEvidence("Invalid invoice line")
    line_parent = line.get("parent")
    pricing = line.get("pricing")
    period = line.get("period")
    if any(type(value) is not dict for value in (line_parent, pricing, period)):
        raise UnsupportedPaidEvidence("Complete invoice line evidence required")
    line_details = line_parent.get("subscription_item_details")
    price_details = pricing.get("price_details")
    if type(line_details) is not dict or type(price_details) is not dict:
        raise UnsupportedPaidEvidence("Bound invoice pricing required")
    start, end, paid = (
        period.get("start"),
        period.get("end"),
        transitions.get("paid_at"),
    )
    amounts = [
        invoice.get("amount_due"),
        invoice.get("amount_paid"),
        invoice.get("amount_remaining"),
        line.get("amount"),
        line.get("quantity"),
        start,
        end,
        paid,
    ]
    if any(type(value) is not int for value in amounts):
        raise UnsupportedPaidEvidence("Integer money and service times required")
    now = int(timezone.now().timestamp())
    if (
        invoice.get("object") != "invoice"
        or invoice.get("status") != "paid"
        or invoice.get("customer") != customer
        or invoice.get("currency") != "usd"
        or invoice["amount_due"] != contract.cents
        or invoice["amount_paid"] != contract.cents
        or invoice["amount_remaining"] != 0
        or line.get("currency") != "usd"
        or line["amount"] != contract.cents
        or line["quantity"] != 1
        or line_parent.get("type") != "subscription_item_details"
        or line_details.get("subscription") != external_subscription
        or line_details.get("subscription_item") != item_id
        or line_details.get("proration") is not False
        or pricing.get("type") != "price_details"
        or price_details.get("price") != price_id
        or not 0 < start <= paid < end
        or paid > now
        or end - start > 32 * 86400
        or (line.get("invoice") is not None and line["invoice"] != invoice_id)
        or ("object" in line and line["object"] != "line_item")
    ):
        raise UnsupportedPaidEvidence("Invoice does not prove supported Core coverage")
    observation = {
        "invoice": invoice_id,
        "customer": customer,
        "subscription": external_subscription,
        "item": item_id,
        "price": price_id,
        "phase": contract.phase,
        "amount": contract.cents,
        "currency": "usd",
        "start": start,
        "end": end,
        "paid": paid,
        "account": _identity(account_id, "acct_"),
        "livemode": livemode,
    }
    # Exclude delivery event ID: duplicate invoice delivery may use another event.
    evidence_digest = hashlib.sha256(rfc8785.dumps(observation)).hexdigest()
    return {
        "schema": "stewardence.paid_coverage.v1",
        "subscription_id": str(subscription_id),
        "stripe_subscription_id": external_subscription,
        "stripe_customer_id": customer,
        "stripe_account_id": observation["account"],
        "livemode": livemode,
        "stripe_invoice_id": invoice_id,
        "stripe_event_id": _identity(event_id, "evt_"),
        "contract_version": "core.monthly.v1",
        "phase": contract.phase,
        "stripe_price_id": price_id,
        "amount_cents": contract.cents,
        "currency": "usd",
        "service_start": start,
        "service_end": end,
        "paid_at": paid,
        "evidence_sha256": evidence_digest,
    }
