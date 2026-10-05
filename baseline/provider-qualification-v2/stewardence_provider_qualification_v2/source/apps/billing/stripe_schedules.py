from __future__ import annotations

from datetime import UTC, datetime

import stripe

from .catalog import PORTFOLIOS
from .pricing import portfolio_price_ids, subscription_price_contract


def _object_value(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)

    return getattr(obj, name, default)


def _phase_value(phase, name, default=None):
    if isinstance(phase, dict):
        return phase.get(name, default)

    return getattr(phase, name, default)


def _founder_metadata(*, subscription):
    return {
        "stewardence_founder": "true",
        "stewardence_founder_sequence": str(subscription.founder_sequence),
        "stewardence_billing_customer_id": str(subscription.billing_customer_id),
    }


def ensure_founder_subscription_schedule(
    *,
    subscription,
):
    """
    Attach and configure the durable founder price schedule.

    Phase 1:
        Founder intro price for six monthly billing periods.

    Phase 2:
        Founder ongoing price indefinitely.

    Both Stripe mutations use stable idempotency keys derived from the
    Stripe subscription identity. Retrying after a local transaction
    failure therefore converges on the same external schedule.
    """
    if not subscription.is_founder:
        raise RuntimeError("Founder schedule requires founder entitlement.")

    if not subscription.founder_sequence:
        raise RuntimeError("Founder schedule requires founder sequence.")

    stripe_subscription_id = subscription.stripe_subscription_id

    if not stripe_subscription_id:
        raise RuntimeError("Founder schedule requires Stripe subscription ID.")

    founder_intro_price_id = portfolio_price_ids(subscription.portfolio)[
        "founder_intro"
    ]

    founder_ongoing_price_id = portfolio_price_ids(subscription.portfolio)[
        "founder_ongoing"
    ]

    if not founder_intro_price_id:
        raise RuntimeError("Founder intro Stripe price is not configured.")

    if not founder_ongoing_price_id:
        raise RuntimeError("Founder ongoing Stripe price is not configured.")

    create_key = f"stewardence-founder-schedule-create:{stripe_subscription_id}"

    configure_key = (
        f"stewardence-founder-schedule-configure-v1:{stripe_subscription_id}"
    )

    if subscription.stripe_schedule_id:
        schedule = stripe.SubscriptionSchedule.retrieve(subscription.stripe_schedule_id)
    else:
        schedule = stripe.SubscriptionSchedule.create(
            from_subscription=stripe_subscription_id,
            idempotency_key=create_key,
        )

    schedule_id = _object_value(schedule, "id")

    if not schedule_id:
        raise RuntimeError("Stripe did not return a subscription schedule ID.")

    current_phase = _object_value(
        schedule,
        "current_phase",
        {},
    )

    current_start = _object_value(
        current_phase,
        "start_date",
    )

    if current_start is None:
        phases = _object_value(
            schedule,
            "phases",
            [],
        )

        if phases:
            current_start = _phase_value(
                phases[0],
                "start_date",
            )

    if current_start is None:
        raise RuntimeError("Stripe founder schedule has no current phase start.")

    metadata = _founder_metadata(
        subscription=subscription,
    )

    configured = stripe.SubscriptionSchedule.modify(
        schedule_id,
        end_behavior="release",
        proration_behavior="none",
        phases=[
            {
                "start_date": current_start,
                "items": [
                    {
                        "price": founder_intro_price_id,
                        "quantity": 1,
                    }
                ],
                "duration": {
                    "interval": "month",
                    "interval_count": PORTFOLIOS[subscription.portfolio][
                        "founder_intro_months"
                    ],
                },
                "proration_behavior": "none",
                "metadata": {
                    **metadata,
                    "stewardence_founder_phase": "intro",
                },
            },
            {
                "items": [
                    {
                        "price": founder_ongoing_price_id,
                        "quantity": 1,
                    }
                ],
                "proration_behavior": "none",
                "metadata": {
                    **metadata,
                    "stewardence_founder_phase": "ongoing",
                },
            },
        ],
        idempotency_key=configure_key,
    )

    phases = _object_value(
        configured,
        "phases",
        [],
    )

    if len(phases) < 2:
        raise RuntimeError("Stripe founder schedule did not return both phases.")

    intro_end_timestamp = _phase_value(
        phases[0],
        "end_date",
    )

    if intro_end_timestamp is None:
        raise RuntimeError("Stripe founder intro phase has no end date.")

    intro_ends_at = datetime.fromtimestamp(
        intro_end_timestamp,
        tz=UTC,
    )

    return {
        "schedule_id": schedule_id,
        "intro_ends_at": intro_ends_at,
    }


def _stripe_subscription_period_end(
    stripe_subscription,
):
    timestamp = _object_value(
        stripe_subscription,
        "current_period_end",
    )

    if timestamp is None:
        items = _object_value(
            stripe_subscription,
            "items",
            {},
        )

        data = _object_value(
            items,
            "data",
            [],
        )

        if data:
            timestamp = _object_value(
                data[0],
                "current_period_end",
            )

    if timestamp is None:
        raise RuntimeError("Stripe subscription has no current billing-period end.")

    return int(timestamp)


def _stripe_subscription_price_id(
    stripe_subscription,
):
    items = _object_value(
        stripe_subscription,
        "items",
        {},
    )

    data = _object_value(
        items,
        "data",
        [],
    )

    if not data:
        raise RuntimeError("Stripe subscription has no active item.")

    price = _object_value(
        data[0],
        "price",
        {},
    )

    price_id = _object_value(
        price,
        "id",
    )

    if not price_id:
        raise RuntimeError("Stripe subscription item has no price ID.")

    return price_id


def _schedule_current_start(
    schedule,
):
    current_phase = _object_value(
        schedule,
        "current_phase",
        {},
    )

    current_start = _object_value(
        current_phase,
        "start_date",
    )

    if current_start is not None:
        return int(current_start)

    phases = _object_value(
        schedule,
        "phases",
        [],
    )

    if phases:
        first_start = _phase_value(
            phases[0],
            "start_date",
        )

        if first_start is not None:
            return int(first_start)

    raise RuntimeError("Founder schedule has no current phase start.")


def _active_founder_schedule(
    subscription,
):
    schedule_id = subscription.stripe_schedule_id

    if not schedule_id:
        return None

    schedule = stripe.SubscriptionSchedule.retrieve(schedule_id)

    status = _object_value(
        schedule,
        "status",
    )

    if status == "active":
        return schedule

    if status in {
        "completed",
        "released",
    }:
        return None

    if status == "canceled":
        raise RuntimeError("Founder schedule is already canceled.")

    raise RuntimeError(f"Founder schedule has unsupported status: {status!r}")


def schedule_founder_cancellation_at_period_end(
    *,
    subscription,
):
    """
    Normalize founder cancel-at-period-end across Stripe's
    two lifecycle-authority modes.

    While an active SubscriptionSchedule owns the subscription,
    truncate that schedule to the current paid billing period and
    set end_behavior=cancel.

    After the founder schedule has naturally completed/released,
    lifecycle authority has returned to the Stripe Subscription,
    so ordinary cancel_at_period_end is used.
    """
    if not subscription.is_founder:
        raise RuntimeError("Founder cancellation requires active founder entitlement.")

    stripe_subscription_id = subscription.stripe_subscription_id

    if not stripe_subscription_id:
        raise RuntimeError("Founder cancellation requires Stripe subscription ID.")

    stripe_subscription = stripe.Subscription.retrieve(stripe_subscription_id)

    period_end = _stripe_subscription_period_end(stripe_subscription)

    active_price_id = _stripe_subscription_price_id(stripe_subscription)

    allowed_prices = {
        portfolio_price_ids(subscription.portfolio)["founder_intro"],
        portfolio_price_ids(subscription.portfolio)["founder_ongoing"],
    }

    if active_price_id not in allowed_prices:
        raise RuntimeError(
            "Founder cancellation found an unexpected active Stripe price."
        )

    schedule = _active_founder_schedule(subscription)

    if schedule is None:
        stripe.Subscription.modify(
            stripe_subscription_id,
            cancel_at_period_end=True,
            idempotency_key=(
                "stewardence-founder-direct-cancel-v1:"
                f"{stripe_subscription_id}:"
                f"{period_end}"
            ),
        )

        return {
            "mode": "subscription",
            "current_period_end": datetime.fromtimestamp(
                period_end,
                tz=UTC,
            ),
            "schedule_id": subscription.stripe_schedule_id,
        }

    schedule_id = _object_value(
        schedule,
        "id",
    )

    current_start = _schedule_current_start(schedule)

    metadata = _founder_metadata(
        subscription=subscription,
    )

    modified = stripe.SubscriptionSchedule.modify(
        schedule_id,
        end_behavior="cancel",
        proration_behavior="none",
        phases=[
            {
                "start_date": current_start,
                "end_date": period_end,
                "items": [
                    {
                        "price": active_price_id,
                        "quantity": 1,
                    }
                ],
                "proration_behavior": "none",
                "metadata": {
                    **metadata,
                    "stewardence_founder_cancel_pending": "true",
                },
            }
        ],
        idempotency_key=(f"stewardence-founder-cancel-v1:{schedule_id}:{period_end}"),
    )

    if (
        _object_value(
            modified,
            "end_behavior",
        )
        != "cancel"
    ):
        raise RuntimeError("Stripe founder schedule did not enter cancel end behavior.")

    return {
        "mode": "schedule",
        "current_period_end": datetime.fromtimestamp(
            period_end,
            tz=UTC,
        ),
        "schedule_id": schedule_id,
    }


def undo_founder_cancellation(
    *,
    subscription,
):
    """
    Restore founder continuity without restarting the intro clock.

    If the founder schedule still owns lifecycle, reconstruct the
    remaining original founder contract around the persisted
    founder_intro_ends_at boundary.

    If the schedule has already completed/released, ordinary Stripe
    Subscription cancellation authority is restored instead.
    """
    if not subscription.is_founder:
        raise RuntimeError(
            "Founder cancellation undo requires active founder entitlement."
        )

    if subscription.status != subscription.Status.CANCELING:
        raise RuntimeError("Founder cancellation undo requires local CANCELING state.")

    stripe_subscription_id = subscription.stripe_subscription_id

    if not stripe_subscription_id:
        raise RuntimeError("Founder cancellation undo requires Stripe subscription ID.")

    stripe_subscription = stripe.Subscription.retrieve(stripe_subscription_id)

    active_price_id = _stripe_subscription_price_id(stripe_subscription)

    schedule = _active_founder_schedule(subscription)

    if schedule is None:
        stripe.Subscription.modify(
            stripe_subscription_id,
            cancel_at_period_end=False,
            idempotency_key=(
                f"stewardence-founder-direct-undo-v1:{stripe_subscription_id}"
            ),
        )

        return {
            "mode": "subscription",
            "schedule_id": subscription.stripe_schedule_id,
        }

    schedule_id = _object_value(
        schedule,
        "id",
    )

    current_start = _schedule_current_start(schedule)

    metadata = _founder_metadata(
        subscription=subscription,
    )

    intro_price_id = portfolio_price_ids(subscription.portfolio)["founder_intro"]

    ongoing_price_id = portfolio_price_ids(subscription.portfolio)["founder_ongoing"]

    phases = []

    if active_price_id == intro_price_id:
        if subscription.founder_intro_ends_at is None:
            raise RuntimeError(
                "Founder intro restoration requires the original intro boundary."
            )

        intro_end = int(subscription.founder_intro_ends_at.astimezone(UTC).timestamp())

        if intro_end <= current_start:
            raise RuntimeError(
                "Founder intro restoration boundary "
                "is not after the current phase start."
            )

        phases = [
            {
                "start_date": current_start,
                "end_date": intro_end,
                "items": [
                    {
                        "price": intro_price_id,
                        "quantity": 1,
                    }
                ],
                "proration_behavior": "none",
                "metadata": {
                    **metadata,
                    "stewardence_founder_phase": "intro",
                },
            },
            {
                "items": [
                    {
                        "price": ongoing_price_id,
                        "quantity": 1,
                    }
                ],
                "proration_behavior": "none",
                "metadata": {
                    **metadata,
                    "stewardence_founder_phase": "ongoing",
                },
            },
        ]

    if active_price_id == ongoing_price_id:
        phases = [
            {
                "start_date": current_start,
                "items": [
                    {
                        "price": ongoing_price_id,
                        "quantity": 1,
                    }
                ],
                "proration_behavior": "none",
                "metadata": {
                    **metadata,
                    "stewardence_founder_phase": "ongoing",
                },
            }
        ]

    if not phases:
        raise RuntimeError(
            "Founder cancellation undo found an unexpected active Stripe price."
        )

    restored = stripe.SubscriptionSchedule.modify(
        schedule_id,
        end_behavior="release",
        proration_behavior="none",
        phases=phases,
        idempotency_key=(f"stewardence-founder-undo-v1:{schedule_id}:{current_start}"),
    )

    if (
        _object_value(
            restored,
            "end_behavior",
        )
        != "release"
    ):
        raise RuntimeError("Stripe founder schedule did not restore release behavior.")

    return {
        "mode": "schedule",
        "schedule_id": schedule_id,
    }


def price_cents_from_stripe_subscription(
    stripe_subscription,
):
    """
    Resolve Stewardence's known portfolio price from Stripe's active
    subscription item.

    Unknown prices intentionally return None rather than inventing local
    billing truth.
    """
    contract = subscription_price_contract(stripe_subscription)
    return contract.cents if contract is not None else None
