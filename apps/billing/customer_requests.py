"""Frozen customer create body, bounded retry window and identity CAS.

An app-observed Stripe ID remains an observation, never payment evidence.
Past the 23-hour window, retrieve/reconcile rather than create with a new key.
"""
from django.db import connections
from agentledger.tenancy.context import identity_transaction
from .models import BillingCustomerRequest


def reserve_customer_request(*, customer_id, actor_id, email, name=None, using="default"):
    with identity_transaction(actor_id, using=using):
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT app_private.reserve_customer_request(%s,%s,%s,%s)",
                [customer_id, actor_id, email, name])
            identity = cursor.fetchone()[0]
        return BillingCustomerRequest.objects.using(using).get(pk=identity)


def customer_create_allowed(request_id, *, using="default"):
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT app_private.customer_create_allowed(%s)", [request_id])
        return bool(cursor.fetchone()[0])


def record_customer_observation(request_id, *, actor_id, generation, external_customer_id, using="default"):
    with identity_transaction(actor_id, using=using):
        with connections[using].cursor() as cursor:
            cursor.execute("SELECT app_private.record_customer_observation(%s,%s,%s)",
                [request_id, generation, external_customer_id])
        return BillingCustomerRequest.objects.using(using).get(pk=request_id)
