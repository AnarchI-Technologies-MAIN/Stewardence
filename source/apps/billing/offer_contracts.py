"""Offline quotation contracts. Registration never authorizes checkout or access."""

from dataclasses import dataclass

from .catalog import PORTFOLIOS

AUDIENCES = {
    "core": "Freelancer",
    "automation": "Organization",
    "enterprise": "Corporate",
}
INCLUDED_ENTERPRISE_BRANCHES = PORTFOLIOS["enterprise"]["included_branches"]
FOUNDER_INCLUDED_ENTERPRISE_BRANCHES = PORTFOLIOS["enterprise"][
    "founder_included_branches"
]
ENTERPRISE_EXTRA_BRANCH_CENTS = PORTFOLIOS["enterprise"]["extra_branch_cents"]


@dataclass(frozen=True)
class OfferQuote:
    portfolio: str
    audience: str
    founder: bool
    phase: str
    base_cents: int
    extra_branches: int
    branch_unit_cents: int
    total_cents: int
    currency: str = "usd"
    interval: str = "month"


def quote_offer(portfolio, *, founder=False, phase="standard", branches=None):
    if type(portfolio) is not str or portfolio not in AUDIENCES:
        raise ValueError("Unknown portfolio")
    if type(founder) is not bool:
        raise ValueError("Founder selection must be boolean")
    if type(phase) is not str or phase not in (
        "standard",
        "founder_intro",
        "founder_ongoing",
    ):
        raise ValueError("Unknown price phase")
    if founder != (phase != "standard"):
        raise ValueError("Founder selection and price phase disagree")
    extra = 0
    unit = 0
    if portfolio != "enterprise" and branches is not None:
        raise ValueError("Branch billing belongs to Enterprise")
    if portfolio == "enterprise":
        if type(branches) is not int or not 1 <= branches <= 10000:
            raise ValueError("Enterprise requires a bounded integer branch count")
        included = (
            FOUNDER_INCLUDED_ENTERPRISE_BRANCHES
            if founder
            else INCLUDED_ENTERPRISE_BRANCHES
        )
        extra = max(0, branches - included)
        if extra:
            unit = ENTERPRISE_EXTRA_BRANCH_CENTS
    catalog = PORTFOLIOS[portfolio]
    base = catalog[phase + "_cents"]
    return OfferQuote(
        portfolio,
        AUDIENCES[portfolio],
        founder,
        phase,
        base,
        extra,
        unit,
        base + extra * unit,
    )
