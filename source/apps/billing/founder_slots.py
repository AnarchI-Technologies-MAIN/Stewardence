from __future__ import annotations

from datetime import timedelta
import uuid

from django.db import transaction
from django.utils import timezone

from .catalog import FOUNDER_LIMIT
from .models import FounderSlot


FOUNDER_CHECKOUT_WINDOW = timedelta(minutes=35)


def _ensure_founder_slots(*, using="default"):
    FounderSlot.objects.using(using).bulk_create(
        [
            FounderSlot(sequence=sequence)
            for sequence in range(1, FOUNDER_LIMIT + 1)
        ],
        ignore_conflicts=True,
    )


def _reset_reservation(slot, *, using):
    slot.billing_customer_id = None
    slot.reservation_token = None
    slot.stripe_checkout_session_id = None
    slot.reserved_at = None
    slot.checkout_expires_at = None

    slot.save(
        using=using,
        update_fields=[
            "billing_customer",
            "reservation_token",
            "stripe_checkout_session_id",
            "reserved_at",
            "checkout_expires_at",
        ],
    )


def reserve_founder_slot(
    *,
    billing_customer_id,
    using="default",
):
    """
    Atomically reserve one of the finite founder slots.

    An existing customer's unclaimed reservation remains the same
    generation while it is still live or owns a Stripe Checkout
    session.

    Multiple checkout requests for that customer therefore converge on
    the same reservation token and, through Stripe idempotency, the same
    external Checkout Session.
    """
    with transaction.atomic(using=using):
        _ensure_founder_slots(using=using)

        slots = list(
            FounderSlot.objects.using(using)
            .select_for_update()
            .order_by("sequence")
        )

        now = timezone.now()

        for slot in slots:
            if slot.billing_customer_id != billing_customer_id:
                continue

            if slot.claimed_at is not None:
                return None

            if slot.stripe_checkout_session_id is not None:
                return slot

            if (
                slot.reservation_token is not None
                and slot.checkout_expires_at is not None
                and slot.checkout_expires_at > now
            ):
                return slot

            slot.reservation_token = uuid.uuid4()
            slot.stripe_checkout_session_id = None
            slot.reserved_at = now
            slot.checkout_expires_at = (
                now + FOUNDER_CHECKOUT_WINDOW
            )

            slot.save(
                using=using,
                update_fields=[
                    "reservation_token",
                    "stripe_checkout_session_id",
                    "reserved_at",
                    "checkout_expires_at",
                ],
            )

            return slot

        for slot in slots:
            if slot.billing_customer_id is not None:
                continue

            slot.billing_customer_id = billing_customer_id
            slot.reservation_token = uuid.uuid4()
            slot.stripe_checkout_session_id = None
            slot.reserved_at = now
            slot.checkout_expires_at = (
                now + FOUNDER_CHECKOUT_WINDOW
            )

            slot.save(
                using=using,
                update_fields=[
                    "billing_customer",
                    "reservation_token",
                    "stripe_checkout_session_id",
                    "reserved_at",
                    "checkout_expires_at",
                ],
            )

            return slot

        return None


def attach_founder_checkout_session(
    *,
    slot_sequence,
    reservation_token,
    billing_customer_id,
    stripe_checkout_session_id,
    checkout_expires_at,
    using="default",
):
    """
    Bind exactly one Stripe Checkout Session to the reservation.

    First attachment wins. Reattaching the same Stripe Session is
    idempotent. A different Session can never replace the authoritative
    one.
    """
    with transaction.atomic(using=using):
        slot = (
            FounderSlot.objects.using(using)
            .select_for_update()
            .filter(sequence=slot_sequence)
            .first()
        )

        if slot is None:
            return False

        if slot.billing_customer_id != billing_customer_id:
            return False

        if str(slot.reservation_token) != str(reservation_token):
            return False

        if slot.claimed_at is not None:
            return False

        if slot.stripe_checkout_session_id is not None:
            return (
                slot.stripe_checkout_session_id
                == stripe_checkout_session_id
            )

        slot.stripe_checkout_session_id = stripe_checkout_session_id
        slot.checkout_expires_at = checkout_expires_at

        slot.save(
            using=using,
            update_fields=[
                "stripe_checkout_session_id",
                "checkout_expires_at",
            ],
        )

        return True


def release_founder_reservation(
    *,
    slot_sequence,
    reservation_token,
    billing_customer_id,
    stripe_checkout_session_id=None,
    using="default",
):
    """
    Release an unclaimed reservation only when its immutable generation
    identity still matches.

    When stripe_checkout_session_id is supplied, the session must match
    as well. This prevents an old expiration event from releasing a
    newer checkout reservation on the same slot.
    """
    with transaction.atomic(using=using):
        slot = (
            FounderSlot.objects.using(using)
            .select_for_update()
            .filter(sequence=slot_sequence)
            .first()
        )

        if slot is None:
            return False

        if slot.billing_customer_id != billing_customer_id:
            return False

        if str(slot.reservation_token) != str(reservation_token):
            return False

        if slot.claimed_at is not None:
            return False

        if stripe_checkout_session_id is not None:
            if (
                slot.stripe_checkout_session_id
                != stripe_checkout_session_id
            ):
                return False

        _reset_reservation(slot, using=using)

        return True


def claim_founder_slot(
    *,
    slot_sequence,
    reservation_token,
    billing_customer_id,
    stripe_checkout_session_id,
    using="default",
):
    """
    Permanently claim the reservation presented by a completed Stripe
    Checkout session.

    The same exact claim is idempotent. Any stale or mismatched
    generation is rejected.
    """
    with transaction.atomic(using=using):
        slot = (
            FounderSlot.objects.using(using)
            .select_for_update()
            .filter(sequence=slot_sequence)
            .first()
        )

        if slot is None:
            return None

        if slot.billing_customer_id != billing_customer_id:
            return None

        if str(slot.reservation_token) != str(reservation_token):
            return None

        if (
            slot.stripe_checkout_session_id
            != stripe_checkout_session_id
        ):
            return None

        if slot.claimed_at is None:
            slot.claimed_at = timezone.now()

            slot.save(
                using=using,
                update_fields=[
                    "claimed_at",
                ],
            )

        return slot


def release_unattached_founder_reservation(
    *,
    slot_sequence,
    reservation_token,
    billing_customer_id,
    using="default",
):
    """
    Release only a reservation that has no authoritative Stripe
    Checkout Session.

    A failed concurrent request therefore cannot erase a winner that
    attached between reservation and cleanup.
    """
    with transaction.atomic(using=using):
        slot = (
            FounderSlot.objects.using(using)
            .select_for_update()
            .filter(sequence=slot_sequence)
            .first()
        )

        if slot is None:
            return False

        if slot.billing_customer_id != billing_customer_id:
            return False

        if str(slot.reservation_token) != str(reservation_token):
            return False

        if slot.claimed_at is not None:
            return False

        if slot.stripe_checkout_session_id is not None:
            return False

        _reset_reservation(slot, using=using)

        return True


def release_expired_founder_checkout(
    *,
    slot_sequence,
    reservation_token,
    billing_customer_id,
    stripe_checkout_session_id,
    using="default",
):
    return release_founder_reservation(
        slot_sequence=slot_sequence,
        reservation_token=reservation_token,
        billing_customer_id=billing_customer_id,
        stripe_checkout_session_id=stripe_checkout_session_id,
        using=using,
    )
