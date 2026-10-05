"""Explicit owner stop of positively unused frozen work; no object deletion."""

from uuid import UUID

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections

from agentledger.tenancy.context import identity_transaction, tenant_transaction

from .models import CycleEvent

REASONS = frozenset({"context_too_large", "owner_stopped"})


def stop_unused_pack(
    *,
    pack_id,
    organization_id,
    actor_id,
    reason,
    using="default",
):
    """Return the immutable stop receipt; admission and replay use current owner.

    Paid expiry and pause do not remove the ability to stop unused work. This
    operation cannot cancel admitted jobs or erase an ambiguous storage outcome.
    """
    if not getattr(settings, "REVIEW_UNUSED_STOP_ENABLED", False):
        raise ValidationError("Unused review stop deployment gate closed")
    if any(
        not isinstance(value, UUID) for value in (pack_id, organization_id, actor_id)
    ):
        raise ValidationError("Exact unused review identities required")
    if type(reason) is not str or reason not in REASONS:
        raise ValidationError("Explicit unused review stop reason required")
    with (
        identity_transaction(actor_id, using=using),
        tenant_transaction(organization_id, using=using),
        connections[using].cursor() as cursor,
    ):
        cursor.execute(
            "SELECT app_private.stop_unused_review_pack(%s,%s,%s,%s)",
            [pack_id, organization_id, actor_id, reason],
        )
        event_id = cursor.fetchone()[0]
        return CycleEvent.objects.using(using).get(
            id=event_id,
            organization_id=organization_id,
        )
