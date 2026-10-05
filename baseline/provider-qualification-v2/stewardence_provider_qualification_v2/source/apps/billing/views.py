from __future__ import annotations

from datetime import UTC, datetime

import stripe
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from agentledger.tenancy.context import identity_transaction

from .catalog import FOUNDER_LIMIT, PORTFOLIOS
from .founder_slots import (
    attach_founder_checkout_session,
    claim_founder_slot,
    release_expired_founder_checkout,
    release_unattached_founder_reservation,
    reserve_founder_slot,
)
from .models import BillingCustomer, StripeWebhookEvent, Subscription
from .pricing import (
    automation_checkout_available,
    portfolio_price_ids,
    subscription_price_contract,
    validate_price_object,
)
from .security import (
    billing_identity,
    founder_claimed_count,
    invoice_subscription_id,
    verified_event_user,
)
from .stripe_schedules import (
    ensure_founder_subscription_schedule,
    price_cents_from_stripe_subscription,
    schedule_founder_cancellation_at_period_end,
    undo_founder_cancellation,
)


def _stripe_client() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured.")

    stripe.api_key = settings.STRIPE_SECRET_KEY


def _subscription_for_user(user_id):
    return (
        Subscription.objects.filter(
            billing_customer__user_id=user_id,
        )
        .select_related("billing_customer")
        .first()
    )


@login_required
@billing_identity
def portfolio_view(request):
    subscription = _subscription_for_user(request.user.id)

    if subscription and subscription.grants_access:
        return redirect("organizations:workspace-selection")

    founder_claimed = founder_claimed_count()

    founder_remaining = max(
        FOUNDER_LIMIT - founder_claimed,
        0,
    )

    return render(
        request,
        "billing/portfolio.html",
        {
            "portfolios": PORTFOLIOS,
            "automation_available": automation_checkout_available(),
            "founder_limit": FOUNDER_LIMIT,
            "founder_claimed": founder_claimed,
            "founder_remaining": founder_remaining,
            "founder_offer_active": founder_remaining > 0,
        },
    )


@login_required
@require_POST
@billing_identity
def start_core_checkout(request):
    return _start_checkout(request, Subscription.Portfolio.CORE)


@login_required
@require_POST
@billing_identity
def start_automation_checkout(request):
    if not automation_checkout_available():
        return HttpResponse("Automation is not yet available for purchase.", status=503)
    return _start_checkout(request, Subscription.Portfolio.AUTOMATION)


def _start_checkout(request, portfolio):
    existing = _subscription_for_user(request.user.id)
    if existing is not None and existing.grants_access:
        return redirect("billing:account")
    prices = portfolio_price_ids(portfolio)
    _stripe_client()

    billing_customer, _ = BillingCustomer.objects.get_or_create(
        user=request.user,
    )

    if billing_customer.stripe_customer_id:
        stripe_customer_id = billing_customer.stripe_customer_id
    else:
        customer = stripe.Customer.create(
            email=request.user.email,
            name=request.user.get_full_name() or None,
            metadata={
                "stewardence_user_id": str(request.user.id),
            },
        )

        stripe_customer_id = customer.id
        billing_customer.stripe_customer_id = stripe_customer_id

        billing_customer.save(
            update_fields=[
                "stripe_customer_id",
                "updated_at",
            ]
        )

    success_url = request.build_absolute_uri(reverse("billing:checkout-success"))

    cancel_url = request.build_absolute_uri(reverse("billing:portfolio"))

    founder_slot = reserve_founder_slot(
        billing_customer_id=billing_customer.id,
    )

    if founder_slot is not None and founder_slot.stripe_checkout_session_id:
        existing_session = stripe.checkout.Session.retrieve(
            founder_slot.stripe_checkout_session_id
        )

        existing_status = existing_session.get("status")
        existing_portfolio = existing_session.get("metadata", {}).get(
            "portfolio", "core"
        )
        if existing_status in {"open", "complete"} and existing_portfolio != portfolio:
            return HttpResponse(
                "A checkout for another plan is already pending. "
                "Complete it or let it expire before choosing another plan.",
                status=409,
            )

        if existing_status == "open":
            existing_url = existing_session.get("url")

            if not existing_url:
                raise RuntimeError(
                    "Authoritative founder Checkout Session has no redirect URL."
                )

            return redirect(existing_url)

        if existing_status == "complete":
            return redirect(
                f"{success_url}?session_id={founder_slot.stripe_checkout_session_id}"
            )

        if existing_status == "expired":
            released = release_expired_founder_checkout(
                slot_sequence=founder_slot.sequence,
                reservation_token=founder_slot.reservation_token,
                billing_customer_id=billing_customer.id,
                stripe_checkout_session_id=(founder_slot.stripe_checkout_session_id),
            )

            if not released:
                raise RuntimeError(
                    "Expired founder Checkout Session could "
                    "not release its exact reservation."
                )

            founder_slot = reserve_founder_slot(
                billing_customer_id=billing_customer.id,
            )

        if existing_status not in {
            "open",
            "complete",
            "expired",
        }:
            raise RuntimeError(
                "Authoritative founder Checkout Session has "
                f"unsupported Stripe status: {existing_status!r}"
            )

    price_id = prices["standard"]

    metadata = {
        "stewardence_user_id": str(request.user.id),
        "portfolio": portfolio,
    }

    if founder_slot is not None:
        price_id = prices["founder_intro"]

        metadata.update(
            {
                "founder_slot_sequence": str(founder_slot.sequence),
                "founder_reservation_token": str(founder_slot.reservation_token),
            }
        )

    if not price_id:
        if founder_slot is not None:
            release_unattached_founder_reservation(
                slot_sequence=founder_slot.sequence,
                reservation_token=founder_slot.reservation_token,
                billing_customer_id=billing_customer.id,
            )

        raise RuntimeError("The selected Stripe price is not configured.")

    checkout_kwargs = {
        "mode": "subscription",
        "customer": stripe_customer_id,
        "client_reference_id": str(request.user.id),
        "line_items": [
            {
                "price": price_id,
                "quantity": 1,
            }
        ],
        "success_url": (f"{success_url}?session_id={{CHECKOUT_SESSION_ID}}"),
        "cancel_url": cancel_url,
        "metadata": metadata,
        "subscription_data": {
            "metadata": metadata,
        },
    }

    if founder_slot is not None:
        checkout_kwargs["expires_at"] = int(
            founder_slot.checkout_expires_at.timestamp()
        )

    create_kwargs = {}

    if founder_slot is not None:
        create_kwargs["idempotency_key"] = (
            f"stewardence-founder-checkout:{founder_slot.reservation_token}"
        )

    try:
        session = stripe.checkout.Session.create(
            **checkout_kwargs,
            **create_kwargs,
        )
    except Exception:
        if founder_slot is not None:
            release_unattached_founder_reservation(
                slot_sequence=founder_slot.sequence,
                reservation_token=founder_slot.reservation_token,
                billing_customer_id=billing_customer.id,
            )

        raise

    if founder_slot is not None:
        attached = attach_founder_checkout_session(
            slot_sequence=founder_slot.sequence,
            reservation_token=founder_slot.reservation_token,
            billing_customer_id=billing_customer.id,
            stripe_checkout_session_id=session.id,
            checkout_expires_at=founder_slot.checkout_expires_at,
        )

        if not attached:
            raise RuntimeError(
                "Stripe returned a Checkout Session that "
                "does not match the authoritative founder "
                "reservation generation."
            )

    return redirect(session.url)


@login_required
@billing_identity
def billing_portal(request):
    _stripe_client()

    billing_customer = BillingCustomer.objects.filter(
        user=request.user,
    ).first()

    if billing_customer is None or not billing_customer.stripe_customer_id:
        raise RuntimeError("No Stripe billing customer exists for this account.")

    subscription = _subscription_for_user(request.user.id)

    configuration_id = settings.STRIPE_BILLING_PORTAL_CONFIGURATION_ID

    if (
        subscription is not None
        and subscription.is_founder
        and subscription.grants_access
    ):
        configuration_id = settings.STRIPE_BILLING_PORTAL_FOUNDER_CONFIGURATION_ID

    if not configuration_id:
        raise RuntimeError(
            "The required Stripe Billing Portal configuration is not configured."
        )

    return_url = request.build_absolute_uri(
        reverse("organizations:workspace-selection")
    )

    portal_session = stripe.billing_portal.Session.create(
        customer=(billing_customer.stripe_customer_id),
        configuration=configuration_id,
        return_url=return_url,
    )

    if not portal_session.url:
        raise RuntimeError("Stripe Billing Portal returned no URL.")

    return redirect(portal_session.url)


@login_required
@require_POST
@billing_identity
def founder_cancel(request):
    _stripe_client()

    subscription = _subscription_for_user(request.user.id)

    if subscription is None:
        raise RuntimeError("No Stewardence subscription exists.")

    if not subscription.is_founder:
        raise RuntimeError("Founder cancellation requires active founder entitlement.")

    if not subscription.grants_access:
        raise RuntimeError("Founder subscription is not active.")

    result = schedule_founder_cancellation_at_period_end(
        subscription=subscription,
    )

    subscription.status = Subscription.Status.CANCELING

    subscription.cancel_at_period_end = True

    period_end = result.get("current_period_end")

    update_fields = [
        "status",
        "cancel_at_period_end",
        "updated_at",
    ]

    if period_end is not None:
        subscription.current_period_end = period_end

        update_fields.append("current_period_end")

    subscription.save(update_fields=update_fields)

    return redirect("organizations:workspace-selection")


@login_required
@require_POST
@billing_identity
def founder_cancel_undo(request):
    _stripe_client()

    subscription = _subscription_for_user(request.user.id)

    if subscription is None:
        raise RuntimeError("No Stewardence subscription exists.")

    undo_founder_cancellation(
        subscription=subscription,
    )

    subscription.status = Subscription.Status.ACTIVE

    subscription.cancel_at_period_end = False

    subscription.save(
        update_fields=[
            "status",
            "cancel_at_period_end",
            "updated_at",
        ]
    )

    return redirect("organizations:workspace-selection")


@login_required
@billing_identity
def billing_account(request):
    subscription = _subscription_for_user(request.user.id)

    billing_customer = BillingCustomer.objects.filter(
        user=request.user,
    ).first()

    can_manage_billing = bool(
        billing_customer is not None and billing_customer.stripe_customer_id
    )

    founder_cancel_pending = bool(
        subscription is not None
        and subscription.is_founder
        and subscription.grants_access
        and subscription.status == Subscription.Status.CANCELING
        and subscription.cancel_at_period_end
    )

    founder_can_cancel = bool(
        subscription is not None
        and subscription.is_founder
        and subscription.grants_access
        and not founder_cancel_pending
    )

    monthly_price_display = None

    if subscription is not None and subscription.current_price_cents is not None:
        monthly_price_display = f"${subscription.current_price_cents / 100:.2f}"

    return render(
        request,
        "billing/account.html",
        {
            "subscription": subscription,
            "can_manage_billing": can_manage_billing,
            "founder_cancel_pending": (founder_cancel_pending),
            "founder_can_cancel": founder_can_cancel,
            "monthly_price_display": (monthly_price_display),
        },
    )


@login_required
@billing_identity
def checkout_success(request):
    subscription = _subscription_for_user(request.user.id)

    return render(
        request,
        "billing/success.html",
        {
            "subscription": subscription,
        },
    )


@csrf_exempt
@require_POST
def stripe_webhook(request: HttpRequest) -> HttpResponse:
    _stripe_client()

    signature = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload=request.body,
            sig_header=signature,
            secret=settings.STRIPE_WEBHOOK_SECRET,
        )
    except (ValueError, stripe.error.SignatureVerificationError):  # noqa: UP039
        return HttpResponse(status=400)

    event_id = event.get("id")
    event_type = event.get("type")

    if not event_id or not event_type:
        return HttpResponse(status=400)

    obj = event["data"]["object"]

    with transaction.atomic():
        _receipt, created = StripeWebhookEvent.objects.get_or_create(
            stripe_event_id=event_id,
            defaults={
                "event_type": event_type,
            },
        )

        if not created:
            return HttpResponse(status=200)

        user_id = verified_event_user(event_type, obj)
        if user_id is None:
            return HttpResponse(status=200)

        with identity_transaction(user_id):
            if event_type in {
                "checkout.session.completed",
                "checkout.session.async_payment_succeeded",
            }:
                _handle_checkout_completed(obj)

            if event_type == "checkout.session.expired":
                _handle_checkout_expired(obj)

            if event_type == "customer.subscription.updated":
                _handle_subscription_updated(obj)

            if event_type in {
                "subscription_schedule.updated",
                "subscription_schedule.completed",
                "subscription_schedule.released",
            }:
                _handle_subscription_schedule_event(obj)

            if event_type == "customer.subscription.deleted":
                _handle_subscription_deleted(obj)

            if event_type == "invoice.paid":
                _handle_invoice_paid(obj)

            if event_type == "invoice.payment_failed":
                _handle_invoice_payment_failed(obj)

    return HttpResponse(status=200)


def _validate_automation_checkout(session, billing_customer):
    if (
        session.get("mode") != "subscription"
        or session.get("payment_status") not in {"paid", "no_payment_required"}
        or session.get("customer") != billing_customer.stripe_customer_id
        or session.get("metadata", {}).get("stewardence_user_id")
        != str(billing_customer.user_id)
        or not session.get("subscription")
    ):
        raise RuntimeError("Automation checkout identity or payment is unverified.")
    authoritative = stripe.Subscription.retrieve(session["subscription"])
    contract = subscription_price_contract(authoritative)
    expected_phase = (
        "founder_intro"
        if session.get("metadata", {}).get("founder_slot_sequence")
        else "standard"
    )
    if (
        contract is None
        or contract.portfolio != "automation"
        or contract.phase != expected_phase
        or authoritative.get("customer") != billing_customer.stripe_customer_id
        or authoritative.get("status") != "active"
        or authoritative.get("metadata", {}).get("portfolio") != "automation"
        or authoritative.get("metadata", {}).get("stewardence_user_id")
        != str(billing_customer.user_id)
    ):
        raise RuntimeError(
            "Automation subscription does not match its paid price contract."
        )
    validate_price_object(authoritative["items"]["data"][0]["price"], contract)
    return authoritative


def _handle_checkout_completed(session) -> None:
    user_id = session.get("client_reference_id")

    billing_customer = BillingCustomer.objects.filter(
        user_id=user_id,
    ).first()

    if billing_customer is None:
        return

    metadata = session.get("metadata", {})

    portfolio = metadata.get("portfolio", Subscription.Portfolio.CORE)
    if portfolio not in {
        Subscription.Portfolio.CORE,
        Subscription.Portfolio.AUTOMATION,
    }:
        raise RuntimeError("Checkout completion has an unsupported portfolio.")
    if session.get("payment_status") == "unpaid":
        return
    authoritative = None
    if portfolio == Subscription.Portfolio.AUTOMATION:
        authoritative = _validate_automation_checkout(session, billing_customer)

    raw_slot_sequence = metadata.get("founder_slot_sequence")

    reservation_token = metadata.get("founder_reservation_token")

    founder_metadata_present = bool(raw_slot_sequence or reservation_token)

    founder_slot = None

    if founder_metadata_present:
        if not raw_slot_sequence or not reservation_token:
            raise RuntimeError(
                "Founder Checkout completion has incomplete reservation metadata."
            )

        try:
            slot_sequence = int(raw_slot_sequence)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                "Founder Checkout completion has invalid slot sequence."
            ) from exc

        founder_slot = claim_founder_slot(
            slot_sequence=slot_sequence,
            reservation_token=reservation_token,
            billing_customer_id=billing_customer.id,
            stripe_checkout_session_id=session.get("id"),
        )

        if founder_slot is None:
            raise RuntimeError(
                "Founder Checkout completion could not prove "
                "its authoritative reservation."
            )

    subscription, _ = Subscription.objects.get_or_create(
        billing_customer=billing_customer,
        defaults={
            "portfolio": portfolio,
        },
    )
    if (
        subscription.grants_access
        and subscription.stripe_subscription_id
        and subscription.stripe_subscription_id != session.get("subscription")
    ):
        raise RuntimeError(
            "An active subscription cannot be replaced by another checkout."
        )
    subscription.portfolio = portfolio

    subscription.stripe_subscription_id = session.get("subscription")
    subscription.status = Subscription.Status.ACTIVE
    if authoritative is not None:
        subscription.current_period_end = _stripe_current_period_end(authoritative)
        if subscription.current_period_end is None:
            raise RuntimeError("Automation checkout is missing its paid period end.")

    if founder_slot is not None:
        subscription.is_founder = True
        subscription.founder_sequence = founder_slot.sequence
        subscription.current_price_cents = PORTFOLIOS[portfolio]["founder_intro_cents"]

        schedule_state = ensure_founder_subscription_schedule(
            subscription=subscription,
        )

        subscription.stripe_schedule_id = schedule_state["schedule_id"]

        subscription.founder_intro_ends_at = schedule_state["intro_ends_at"]

    if founder_slot is None:
        subscription.current_price_cents = PORTFOLIOS[portfolio]["standard_cents"]

        subscription.is_founder = False
        subscription.stripe_schedule_id = None
        subscription.founder_intro_ends_at = None

    subscription.save()


def _handle_checkout_expired(session) -> None:
    user_id = session.get("client_reference_id")

    billing_customer = BillingCustomer.objects.filter(
        user_id=user_id,
    ).first()

    if billing_customer is None:
        return

    metadata = session.get("metadata", {})

    slot_sequence = metadata.get("founder_slot_sequence")
    reservation_token = metadata.get("founder_reservation_token")

    if not slot_sequence or not reservation_token:
        return

    try:
        slot_sequence = int(slot_sequence)
    except (TypeError, ValueError):  # noqa: UP039
        return

    release_expired_founder_checkout(
        slot_sequence=slot_sequence,
        reservation_token=reservation_token,
        billing_customer_id=billing_customer.id,
        stripe_checkout_session_id=session.get("id"),
    )


def _stripe_current_period_end(
    stripe_subscription,
):
    """
    Return Stripe's authoritative paid-period end.

    Prefer the subscription-level field. Fall back to the first
    subscription item for API shapes where period boundaries are
    represented there.
    """
    timestamp = stripe_subscription.get("current_period_end")

    if timestamp is None:
        items = stripe_subscription.get(
            "items",
            {},
        )

        data = items.get("data", [])

        if data:
            timestamp = data[0].get("current_period_end")

    if timestamp is None:
        return None

    return datetime.fromtimestamp(
        int(timestamp),
        tz=UTC,
    )


def _handle_subscription_updated(stripe_subscription) -> None:
    subscription = Subscription.objects.filter(
        stripe_subscription_id=stripe_subscription["id"],
    ).first()

    if subscription is None:
        return

    contract = subscription_price_contract(stripe_subscription)
    if subscription.portfolio == Subscription.Portfolio.AUTOMATION and contract is None:
        subscription.status = Subscription.Status.PENDING
        subscription.save(update_fields=["status", "updated_at"])
        return
    if contract is not None:
        if subscription.is_founder and contract.portfolio != subscription.portfolio:
            raise RuntimeError(
                "Founder plan changes require an explicit price-contract transition."
            )
        subscription.portfolio = contract.portfolio

    stripe_status = stripe_subscription.get(
        "status",
        "",
    )

    status_map = {
        "active": Subscription.Status.ACTIVE,
        "trialing": Subscription.Status.ACTIVE,
        "past_due": Subscription.Status.PAST_DUE,
        "canceled": Subscription.Status.CANCELED,
    }

    mapped = status_map.get(stripe_status)

    founder_normalized_cancel = bool(
        subscription.is_founder and subscription.status == Subscription.Status.CANCELING
    )

    if mapped:
        subscription.status = mapped

    stripe_cancel_at_period_end = bool(stripe_subscription.get("cancel_at_period_end"))

    if founder_normalized_cancel:
        subscription.status = Subscription.Status.CANCELING

        subscription.cancel_at_period_end = True

    if not founder_normalized_cancel:
        subscription.cancel_at_period_end = stripe_cancel_at_period_end

        if (
            subscription.status == Subscription.Status.ACTIVE
            and subscription.cancel_at_period_end
        ):
            subscription.status = Subscription.Status.CANCELING

    period_end = _stripe_current_period_end(stripe_subscription)

    stripe_price_cents = price_cents_from_stripe_subscription(stripe_subscription)

    update_fields = [
        "status",
        "cancel_at_period_end",
        "updated_at",
    ]

    if contract is not None:
        update_fields.append("portfolio")

    if period_end is not None:
        subscription.current_period_end = period_end

        update_fields.append("current_period_end")

    if stripe_price_cents is not None:
        subscription.current_price_cents = stripe_price_cents

        update_fields.append("current_price_cents")

    stripe_schedule_id = stripe_subscription.get("schedule")

    if stripe_schedule_id:
        subscription.stripe_schedule_id = stripe_schedule_id

        update_fields.append("stripe_schedule_id")

    subscription.save(update_fields=update_fields)


def _handle_subscription_schedule_event(
    stripe_schedule,
) -> None:
    schedule_id = stripe_schedule.get("id")

    if not schedule_id:
        return

    subscription = Subscription.objects.filter(
        stripe_schedule_id=schedule_id,
    ).first()

    if subscription is None:
        return

    if not subscription.is_founder:
        return

    schedule_status = stripe_schedule.get(
        "status",
        "",
    )

    end_behavior = stripe_schedule.get(
        "end_behavior",
        "",
    )

    if schedule_status == "active" and end_behavior == "cancel":
        subscription.status = Subscription.Status.CANCELING

        subscription.cancel_at_period_end = True

        subscription.save(
            update_fields=[
                "status",
                "cancel_at_period_end",
                "updated_at",
            ]
        )

        return

    if (
        schedule_status == "active"
        and end_behavior == "release"
        and subscription.status == Subscription.Status.CANCELING
    ):
        subscription.status = Subscription.Status.ACTIVE

        subscription.cancel_at_period_end = False

        subscription.save(
            update_fields=[
                "status",
                "cancel_at_period_end",
                "updated_at",
            ]
        )


def _handle_subscription_deleted(stripe_subscription) -> None:
    subscription = Subscription.objects.filter(
        stripe_subscription_id=stripe_subscription["id"],
    ).first()

    if subscription is None:
        return

    subscription.status = Subscription.Status.CANCELED

    subscription.cancel_at_period_end = False

    period_end = _stripe_current_period_end(stripe_subscription)

    update_fields = [
        "status",
        "cancel_at_period_end",
        "updated_at",
    ]

    if period_end is not None:
        subscription.current_period_end = period_end

        update_fields.append("current_period_end")

    if subscription.is_founder and subscription.founder_entitlement_ends_on_cancel:
        subscription.is_founder = False

        subscription.stripe_schedule_id = None
        subscription.founder_intro_ends_at = None

        update_fields.extend(
            [
                "is_founder",
                "stripe_schedule_id",
                "founder_intro_ends_at",
            ]
        )

    subscription.save(update_fields=update_fields)


def _handle_invoice_paid(invoice) -> None:
    subscription_id = invoice_subscription_id(invoice)

    if not subscription_id:
        return

    Subscription.objects.filter(
        stripe_subscription_id=subscription_id,
    ).exclude(
        status__in=[Subscription.Status.CANCELING, Subscription.Status.CANCELED],
    ).update(
        status=Subscription.Status.ACTIVE,
    )


def _handle_invoice_payment_failed(invoice) -> None:
    subscription_id = invoice_subscription_id(invoice)

    if not subscription_id:
        return

    Subscription.objects.filter(
        stripe_subscription_id=subscription_id,
    ).update(
        status=Subscription.Status.PAST_DUE,
    )
