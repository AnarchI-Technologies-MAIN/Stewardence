"""Offline quote admission only: these tests establish no purchase entitlement."""

from dataclasses import FrozenInstanceError
from decimal import Decimal

import pytest

from apps.billing.offer_contracts import quote_offer


class StringAlias(str):
    """A caller-controlled subclass is not a canonical contract identifier."""


class IntegerAlias(int):
    pass


@pytest.mark.parametrize("branches", [1, 4, 5, 6, 7, 10000])
@pytest.mark.parametrize(
    "founder,phase,base,included",
    [(False, "standard", 50000, 4),
     (True, "founder_intro", 35000, 5),
     (True, "founder_ongoing", 40000, 5)],
)
def test_enterprise_boundary_quote_is_exact_integer_arithmetic(
    branches, founder, phase, base, included
):
    quoted = quote_offer("enterprise", founder=founder, phase=phase,
                         branches=branches)
    extra = max(0, branches - included)
    assert quoted.base_cents == base
    assert quoted.extra_branches == extra
    assert quoted.branch_unit_cents == (2500 if extra else 0)
    assert quoted.total_cents == base + extra * 2500
    assert type(quoted.total_cents) is int
    assert (quoted.currency, quoted.interval) == ("usd", "month")


@pytest.mark.parametrize("branches", [
    None, True, False, 0, -1, 10001, 10**100, 1.0, 4.5,
    float("nan"), float("inf"), Decimal("5"), "5", " 5 ",
    [], [5], {}, {"count": 5}, (5,), IntegerAlias(5),
])
def test_branch_count_cannot_coerce_or_embed_quantity(branches):
    with pytest.raises(ValueError):
        quote_offer("enterprise", branches=branches)


@pytest.mark.parametrize("portfolio", [
    None, True, 1, "", "Enterprise", "enterprise ", "enterprise\x00",
    "corporate", "organization", "freelancer", [], {},
    StringAlias("enterprise"),
])
def test_portfolio_requires_canonical_registered_identifier(portfolio):
    with pytest.raises(ValueError):
        quote_offer(portfolio, branches=5)


@pytest.mark.parametrize("phase", [
    None, True, 1, "", "STANDARD", "standard ", "standard\x00",
    "founder", "founder_forever", [], {}, ("standard",),
    StringAlias("standard"),
])
def test_phase_requires_canonical_registered_identifier(phase):
    with pytest.raises(ValueError):
        quote_offer("core", phase=phase)


@pytest.mark.parametrize("founder", [None, 0, 1, "true", "false", [], {}])
def test_founder_selection_is_boolean_not_truthiness(founder):
    with pytest.raises(ValueError):
        quote_offer("core", founder=founder)


@pytest.mark.parametrize("founder,phase", [
    (True, "standard"), (False, "founder_intro"), (False, "founder_ongoing"),
])
@pytest.mark.parametrize("portfolio", ["core", "automation", "enterprise"])
def test_founder_phase_mismatch_never_changes_contract(founder, phase, portfolio):
    with pytest.raises(ValueError):
        quote_offer(portfolio, founder=founder, phase=phase,
                    branches=5 if portfolio == "enterprise" else None)


@pytest.mark.parametrize("portfolio", ["core", "automation"])
@pytest.mark.parametrize("branches", [0, 1, False, "5", [], {}])
def test_nonenterprise_cannot_smuggle_branch_quantity(portfolio, branches):
    with pytest.raises(ValueError):
        quote_offer(portfolio, branches=branches)


def test_quote_is_frozen_and_later_selection_does_not_mutate_earlier_quote():
    selected = {"founder": True, "phase": "founder_intro", "branches": 6}
    first = quote_offer("enterprise", **selected)
    assert selected == {"founder": True, "phase": "founder_intro", "branches": 6}
    selected["branches"] = 7
    second = quote_offer("enterprise", **selected)
    assert first.total_cents == 37500
    assert second.total_cents == 40000
    with pytest.raises(FrozenInstanceError):
        first.total_cents = 0


def test_founder_quote_is_a_selection_not_proof_of_continuity_or_authority():
    quoted = quote_offer("enterprise", founder=True, phase="founder_ongoing",
                         branches=5)
    assert quoted.total_cents == 40000
    assert not hasattr(quoted, "subscription_id")
    assert not hasattr(quoted, "paid_through")
    assert not hasattr(quoted, "agreement_id")
