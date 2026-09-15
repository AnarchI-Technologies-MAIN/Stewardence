from django.urls import path

from .views import (
    billing_account,
    billing_portal,
    checkout_success,
    founder_cancel,
    founder_cancel_undo,
    portfolio_view,
    start_core_checkout,
    stripe_webhook,
)

app_name = "billing"

urlpatterns = [
    path(
        "account/",
        billing_account,
        name="account",
    ),
    path(
        "portfolio/",
        portfolio_view,
        name="portfolio",
    ),
    path(
        "checkout/core/",
        start_core_checkout,
        name="checkout-core",
    ),
    path(
        "portal/",
        billing_portal,
        name="portal",
    ),
    path(
        "founder/cancel/",
        founder_cancel,
        name="founder-cancel",
    ),
    path(
        "founder/cancel/undo/",
        founder_cancel_undo,
        name="founder-cancel-undo",
    ),
    path(
        "checkout/success/",
        checkout_success,
        name="checkout-success",
    ),
    path(
        "webhook/stripe/",
        stripe_webhook,
        name="stripe-webhook",
    ),
]
