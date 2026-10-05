from functools import wraps
from uuid import UUID

from django.db import connection

from agentledger.tenancy.context import identity_transaction


def billing_identity(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        with identity_transaction(request.user.id):
            return view(request, *args, **kwargs)

    return wrapped


def founder_claimed_count():
    with connection.cursor() as cursor:
        cursor.execute("SELECT app_private.billing_founder_claimed()")
        return cursor.fetchone()[0]


def invoice_subscription_id(invoice):
    return invoice.get("subscription") or (
        invoice.get("parent", {}).get("subscription_details", {}).get("subscription")
    )


def verified_event_user(event_type, obj):
    """Call only after Stripe's signature verification has succeeded."""
    if event_type.startswith("checkout.session."):
        value = obj.get("client_reference_id")
        try:
            return UUID(str(value))
        except (ValueError, TypeError, AttributeError):  # noqa: UP039
            return None
    is_schedule = event_type.startswith("subscription_schedule.")
    external_id = (
        invoice_subscription_id(obj)
        if event_type.startswith("invoice.")
        else obj.get("id")
    )
    if isinstance(external_id, dict):
        external_id = external_id.get("id")
    if not external_id:
        return None
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT app_private.billing_event_user(%s, %s)", [external_id, is_schedule]
        )
        return cursor.fetchone()[0]
