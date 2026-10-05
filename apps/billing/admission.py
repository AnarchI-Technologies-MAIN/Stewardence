"""Separate credentialed process: no ordinary app connection may issue payment."""

import hashlib
import json
import re

import stripe
from django.conf import settings
from django.db import connection, transaction

from .paid_evidence import UnsupportedPaidEvidence, normalize_paid_invoice
from .pricing import subscription_price_contract


class AdmissionConfigurationError(RuntimeError):
    pass


def configuration():
    secret = getattr(settings, "BILLING_ADMISSION_WEBHOOK_SECRET", "")
    key = getattr(settings, "BILLING_ADMISSION_STRIPE_KEY", "")
    account = getattr(settings, "BILLING_ADMISSION_ACCOUNT_ID", "")
    mode = getattr(settings, "BILLING_ADMISSION_LIVEMODE", None)
    if (
        type(secret) is not str
        or not secret.startswith("whsec_")
        or secret.strip() != secret
        or not secret[6:].strip()
        or type(mode) is not bool
        or type(account) is not str
        or re.fullmatch(r"acct_[A-Za-z0-9_]+", account) is None
        or type(key) is not str
        or not key.startswith("rk_live_" if mode else "rk_test_")
        or len(key) <= 8
    ):
        raise AdmissionConfigurationError("Payment admission is not configured")
    return secret, key, account, mode


def enforce_connection():
    if connection.vendor != "postgresql":
        raise AdmissionConfigurationError("Dedicated admission PostgreSQL required")
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_user,rolsuper,rolbypassrls,current_setting('transaction_isolation') FROM pg_roles WHERE rolname=current_user"
        )
        if cursor.fetchone() != (
            "agentledger_billing_admission",
            False,
            False,
            "read committed",
        ):
            raise AdmissionConfigurationError("Dedicated admission role required")


def _plain(value):
    if isinstance(value, stripe.StripeObject):
        value = value.to_dict()
    if type(value) is not dict:
        raise UnsupportedPaidEvidence("Unrecognized provider response")
    return value


def ingest_verified_event(event, raw_body, *, key, account_id, livemode):
    """Caller authenticates original raw signature; all effects use default only."""
    if event.get("type") != "invoice.paid" or event.get("livemode") is not livemode:
        raise UnsupportedPaidEvidence("Unsupported event or environment")
    if event.get("account") not in (None, account_id):
        raise UnsupportedPaidEvidence("Event account mismatch")
    invoice_id = event.get("data", {}).get("object", {}).get("id")
    event_id = event.get("id")
    if (
        type(invoice_id) is not str
        or re.fullmatch(r"in_[A-Za-z0-9_]+", invoice_id) is None
        or type(event_id) is not str
        or re.fullmatch(r"evt_[A-Za-z0-9_]+", event_id) is None
    ):
        raise UnsupportedPaidEvidence("Unsupported event identity")
    enforce_connection()
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT app_private.committed_paid_admission(%s,%s,%s,%s,%s)",
            [
                account_id,
                livemode,
                event_id,
                "invoice.paid",
                hashlib.sha256(raw_body).hexdigest(),
            ],
        )
        committed = cursor.fetchone()[0]
        if committed is not None:
            return committed
        # Recognizing an exact committed effect does not issue new authority.
        # Current issuance pins are required only for an uncommitted event.
        cursor.execute(
            "SELECT app_private.paid_admission_authority_ready(%s,%s)",
            [account_id, livemode],
        )
        if cursor.fetchone()[0] is not True:
            raise AdmissionConfigurationError("Payment authority is not admitted")
    client = stripe.StripeClient(
        key, max_network_retries=0, http_client=stripe.RequestsClient(timeout=10)
    )
    account = _plain(client.v1.accounts.retrieve_current())
    if account.get("id") != account_id:
        raise UnsupportedPaidEvidence("Retrieved account mismatch")
    invoice = _plain(client.v1.invoices.retrieve(invoice_id))
    if invoice.get("id") != invoice_id:
        raise UnsupportedPaidEvidence("Retrieved invoice mismatch")
    external = (
        invoice.get("parent", {}).get("subscription_details", {}).get("subscription")
    )
    if (
        type(external) is not str
        or re.fullmatch(r"sub_[A-Za-z0-9_]+", external) is None
    ):
        raise UnsupportedPaidEvidence("Missing invoice subscription")
    subscription = _plain(client.v1.subscriptions.retrieve(external))
    if subscription.get("id") != external or subscription.get("status") not in (
        "active",
        "past_due",
    ):
        raise UnsupportedPaidEvidence("Unadmitted subscription state")
    contract = subscription_price_contract(subscription)
    if contract is None or contract.portfolio != "core":
        raise UnsupportedPaidEvidence("Unregistered Core contract")
    metadata = subscription.get("metadata", {})
    if type(metadata) is not dict or metadata.get("portfolio") != "core":
        raise UnsupportedPaidEvidence("Missing Core identity")
    with transaction.atomic():
        enforce_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT app_private.begin_paid_admission(%s,%s,%s,%s,%s,%s,%s)",
                [
                    subscription.get("customer"),
                    external,
                    account_id,
                    livemode,
                    metadata.get("stewardence_user_id"),
                    "core",
                    contract.phase,
                ],
            )
            subscription_id = cursor.fetchone()[0]
            envelope = normalize_paid_invoice(
                invoice,
                subscription,
                subscription_id=subscription_id,
                account_id=account_id,
                livemode=livemode,
                event_id=event_id,
            )
            cursor.execute(
                "SELECT app_private.finish_paid_admission(%s::jsonb,%s,%s)",
                [
                    json.dumps(envelope),
                    "invoice.paid",
                    hashlib.sha256(raw_body).hexdigest(),
                ],
            )
            return cursor.fetchone()[0]
