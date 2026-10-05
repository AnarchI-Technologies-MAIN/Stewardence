"""Frozen test-mode standard checkout; no coverage admission or legacy fallback."""

import re
from urllib.parse import urlsplit

import stripe
from django.conf import settings
from django.db import DatabaseError, connections

from agentledger.tenancy.context import identity_transaction

from .checkout_intents import (
    checkout_create_allowed,
    record_checkout_observation,
    reserve_standard_checkout,
)
from .customer_requests import (
    customer_create_allowed,
    record_customer_observation,
    reserve_customer_request,
)
from .models import BillingCustomer, PaidCoverageAuthority


class CheckoutFlowHeld(RuntimeError):
    """A bounded reconciliation/configuration hold; never includes key values."""


StandardCheckoutHold = CheckoutFlowHeld


def _plain(value):
    if isinstance(value, stripe.StripeObject):
        value = value.to_dict()
    if type(value) is not dict:
        raise StandardCheckoutHold("Unrecognized checkout response")
    return value


def _client(key):
    return stripe.StripeClient(
        key, max_network_retries=0, http_client=stripe.RequestsClient(timeout=10)
    )


def _customer(value, owner, mode):
    value = _plain(value)
    if (
        type(value.get("id")) is not str
        or re.fullmatch(r"cus_[A-Za-z0-9_]+", value["id"]) is None
        or value.get("livemode") is not mode
        or value.get("deleted") is True
        or type(value.get("metadata")) is not dict
        or value["metadata"].get("stewardence_user_id") != str(owner)
    ):
        raise StandardCheckoutHold("Customer observation requires reconciliation")
    return value["id"]


def _session(value, intent, using):
    value = _plain(value)
    params = intent.params
    if (
        type(value.get("id")) is not str
        or re.fullmatch(r"cs_[A-Za-z0-9_]+", value["id"]) is None
        or value.get("customer") != intent.stripe_customer_id
        or value.get("client_reference_id") != params["client_reference_id"]
        or value.get("metadata") != params["metadata"]
        or value.get("mode") != "subscription"
        or value.get("livemode") is not intent.livemode
        or type(value.get("expires_at")) is not int
        or value["expires_at"] != params["expires_at"]
        or value.get("status") != "open"
    ):
        raise StandardCheckoutHold("Checkout observation requires reconciliation")
    url = value.get("url")
    if type(url) is not str or len(url) > 2048 or any(c.isspace() for c in url):
        raise StandardCheckoutHold("Checkout redirect unavailable")
    try:
        parsed = urlsplit(url)
    except ValueError as error:
        raise StandardCheckoutHold("Checkout redirect unavailable") from error
    if (
        parsed.scheme != "https"
        or parsed.netloc != "checkout.stripe.com"
        or not parsed.path.startswith("/")
    ):
        raise StandardCheckoutHold("Checkout redirect unavailable")
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT clock_timestamp()")
        if intent.expires_at <= cursor.fetchone()[0]:
            raise StandardCheckoutHold("Checkout session is held after expiry")
    return value["id"], url


def start_standard_checkout(user, success_url, cancel_url, *, using="default"):
    """Persist each request before writing externally; return only validated URL.

    No enclosing transaction is allowed: otherwise an ambiguous response could
    roll back its idempotency generation and let a subsequent request create anew.
    """
    if getattr(settings, "STANDARD_CHECKOUT_INTENTS_ENABLED", False) is not True:
        raise StandardCheckoutHold("Standard checkout is not enabled")
    if connections[using].in_atomic_block:
        raise StandardCheckoutHold("Checkout requires independent durable requests")
    key = getattr(settings, "STANDARD_CHECKOUT_STRIPE_KEY", "")
    if (
        type(key) is not str
        or re.fullmatch(r"(?:sk|rk)_test_[A-Za-z0-9]+", key) is None
    ):
        raise StandardCheckoutHold("Test checkout is not configured")
    with identity_transaction(user.id, using=using):
        authority = PaidCoverageAuthority.objects.using(using).filter(pk=1).first()
        if authority is None or authority.livemode is not False:
            raise StandardCheckoutHold("Test checkout authority unavailable")
        contract = (
            authority.contracts.get("standard")
            if type(authority.contracts) is dict
            else None
        )
        if (
            type(contract) is not dict
            or contract.get("contract_version") != "core.monthly.v1"
            or type(contract.get("amount_cents")) is not int
            or contract["amount_cents"] != 9900
            or type(contract.get("price_id")) is not str
        ):
            raise StandardCheckoutHold("Standard checkout contract unavailable")
        customer, _ = BillingCustomer.objects.using(using).get_or_create(
            user_id=user.id
        )
    client = _client(key)
    try:
        account = _plain(client.v1.accounts.retrieve_current())
        if account.get("id") != authority.stripe_account_id:
            raise StandardCheckoutHold("Checkout account mismatch")
        price = _plain(client.v1.prices.retrieve(contract["price_id"]))
        recurring = price.get("recurring")
        if (
            price.get("id") != contract["price_id"]
            or price.get("livemode") is not False
            or price.get("active") is not True
            or price.get("currency") != "usd"
            or type(price.get("unit_amount")) is not int
            or price["unit_amount"] != 9900
            or type(recurring) is not dict
            or recurring.get("interval") != "month"
            or type(recurring.get("interval_count")) is not int
            or recurring["interval_count"] != 1
            or recurring.get("usage_type") != "licensed"
        ):
            raise StandardCheckoutHold("Checkout provider price mismatch")
        if customer.stripe_customer_id:
            observed = _customer(
                client.v1.customers.retrieve(customer.stripe_customer_id),
                user.id,
                False,
            )
            if observed != customer.stripe_customer_id:
                raise StandardCheckoutHold("Checkout customer mismatch")
        if not customer.stripe_customer_id:
            request = reserve_customer_request(
                customer_id=customer.id,
                actor_id=user.id,
                email=user.email,
                name=user.get_full_name() or None,
                using=using,
            )
            if (
                request.stripe_account_id != authority.stripe_account_id
                or request.livemode is not False
            ):
                raise StandardCheckoutHold("Customer request authority changed")
            with identity_transaction(user.id, using=using):
                allowed = customer_create_allowed(request.id, using=using)
            if not allowed:
                raise StandardCheckoutHold(
                    "Customer creation is held for reconciliation"
                )
            response = client.v1.customers.create(
                params=request.params,
                options={"idempotency_key": request.idempotency_key},
            )
            observed = _customer(response, user.id, False)
            record_customer_observation(
                request.id,
                actor_id=user.id,
                generation=request.generation,
                external_customer_id=observed,
                using=using,
            )
        intent = reserve_standard_checkout(
            customer_id=customer.id,
            actor_id=user.id,
            success_url=success_url,
            cancel_url=cancel_url,
            using=using,
        )
        if (
            intent.stripe_account_id != authority.stripe_account_id
            or intent.livemode is not False
        ):
            raise StandardCheckoutHold("Checkout intent authority changed")
        if intent.observed_session_id:
            response = client.v1.checkout.sessions.retrieve(intent.observed_session_id)
            session_id, url = _session(response, intent, using)
            if session_id != intent.observed_session_id or url != intent.observed_url:
                raise StandardCheckoutHold("Checkout session observation changed")
        if not intent.observed_session_id:
            with identity_transaction(user.id, using=using):
                allowed = checkout_create_allowed(intent.id, using=using)
            if not allowed:
                raise StandardCheckoutHold(
                    "Checkout creation is held for reconciliation"
                )
            response = client.v1.checkout.sessions.create(
                params=intent.params,
                options={"idempotency_key": intent.idempotency_key},
            )
            session_id, url = _session(response, intent, using)
            record_checkout_observation(
                intent.id,
                actor_id=user.id,
                generation=intent.generation,
                session_id=session_id,
                url=url,
                using=using,
            )
        return url
    except stripe.StripeError as error:
        raise StandardCheckoutHold(
            "Provider response is ambiguous; retry the retained request"
        ) from error
    except DatabaseError as error:
        raise StandardCheckoutHold("Checkout state requires reconciliation") from error
