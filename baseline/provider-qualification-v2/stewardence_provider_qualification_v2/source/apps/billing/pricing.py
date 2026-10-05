from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings

from .catalog import PORTFOLIOS

SUPPORTED_PORTFOLIOS = ("core", "automation")
PHASES = ("standard", "founder_intro", "founder_ongoing")


@dataclass(frozen=True)
class PriceContract:
    portfolio: str
    phase: str
    cents: int


def portfolio_price_ids(portfolio: str) -> dict[str, str]:
    if portfolio not in SUPPORTED_PORTFOLIOS:
        raise ValueError("Unsupported subscription portfolio")
    return {
        phase: getattr(
            settings, f"STRIPE_{portfolio.upper()}_{phase.upper()}_PRICE_ID", ""
        )
        for phase in PHASES
    }


def configured_price_contracts() -> dict[str, PriceContract]:
    contracts = {}
    for portfolio in SUPPORTED_PORTFOLIOS:
        for phase, price_id in portfolio_price_ids(portfolio).items():
            if not price_id:
                continue
            if price_id in contracts:
                raise ValueError("Stripe price IDs must be distinct for each contract")
            contracts[price_id] = PriceContract(
                portfolio, phase, PORTFOLIOS[portfolio][f"{phase}_cents"]
            )
    return contracts


def automation_checkout_available() -> bool:
    try:
        configured_price_contracts()
    except ValueError:
        return False
    return bool(
        settings.AUTOMATION_ENABLED
        and settings.STRIPE_SECRET_KEY
        and settings.STRIPE_WEBHOOK_SECRET
        and all(portfolio_price_ids("automation").values())
    )


def subscription_price_contract(subscription) -> PriceContract | None:
    items = subscription.get("items", {}).get("data", [])
    if len(items) != 1 or items[0].get("quantity", 1) != 1:
        return None
    price = items[0].get("price", {})
    if not isinstance(price, dict):
        return None
    return configured_price_contracts().get(price.get("id"))


def validate_price_object(price, contract: PriceContract) -> None:
    recurring = price.get("recurring") or {}
    if (
        not price.get("active")
        or price.get("currency") != "usd"
        or price.get("unit_amount") != contract.cents
        or recurring.get("interval") != "month"
        or recurring.get("interval_count", 1) != 1
        or recurring.get("usage_type", "licensed") != "licensed"
    ):
        raise ValueError("Stripe price does not match the monthly portfolio contract")
