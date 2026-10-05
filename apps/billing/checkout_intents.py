"""Durable standard checkout requests; no provider calls or payment issuance.

Only separately trusted admission can attest provider session outcomes. An old
or ambiguous request is retained, never treated as authority to create anew.
"""
from uuid import UUID
from django.db import connections
from agentledger.tenancy.context import identity_transaction
from .models import CheckoutIntent


def customer_creation_idempotency_key(customer_id):
    return "stewardence-customer-v1:" + str(UUID(str(customer_id)))


def reserve_standard_checkout(*, customer_id, actor_id, success_url, cancel_url, using="default"):
    with identity_transaction(actor_id, using=using):
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT app_private.reserve_standard_checkout(%s,%s,%s,%s)",
                [customer_id, actor_id, success_url, cancel_url])
            identity = cursor.fetchone()[0]
        return CheckoutIntent.objects.using(using).get(pk=identity)


def checkout_create_allowed(intent_id, *, using="default"):
    """Server-time bounded create/retry admission, separate from retained state."""
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT app_private.checkout_create_allowed(%s)", [intent_id])
        return bool(cursor.fetchone()[0])


def record_checkout_observation(intent_id, *, actor_id, generation, session_id, url, using="default"):
    """A redirect observation grants no payment or authoritative expiry state."""
    with identity_transaction(actor_id, using=using):
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT app_private.record_checkout_observation(%s,%s,%s,%s)",
                [intent_id, generation, session_id, url])
        return CheckoutIntent.objects.using(using).get(pk=intent_id)


def admit_checkout_outcome(intent_id, *, generation, session_id, status, customer_id,
                           account_id, livemode, expires_at, using="billing_admission"):
    """Called only after authoritative retrieval and full request binding checks."""
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT app_private.admit_checkout_outcome(%s,%s,%s,%s,%s,%s,%s,%s)",
            [intent_id, generation, session_id, status, customer_id, account_id, livemode, expires_at])
        return cursor.fetchone()[0]
