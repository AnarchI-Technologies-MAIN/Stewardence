import pytest

from apps.billing.offer_contracts import quote_offer


@pytest.mark.parametrize(
    "portfolio,standard,intro,ongoing",
    [
        ("core", 9900, 4900, 7500),
        ("automation", 14900, 7500, 11200),
    ],
)
def test_registered_existing_phase_amounts(portfolio, standard, intro, ongoing):
    assert quote_offer(portfolio).total_cents == standard
    assert (
        quote_offer(portfolio, founder=True, phase="founder_intro").total_cents == intro
    )
    assert (
        quote_offer(portfolio, founder=True, phase="founder_ongoing").total_cents
        == ongoing
    )


def test_enterprise_four_included_then_explicit_increment():
    assert quote_offer("enterprise", branches=4).total_cents == 50000
    assert quote_offer("enterprise", branches=5).total_cents == 52500
    assert quote_offer("enterprise", branches=6).total_cents == 55000


def test_founder_has_five_included_and_full_price_addons():
    assert (
        quote_offer(
            "enterprise", founder=True, phase="founder_intro", branches=5
        ).total_cents
        == 35000
    )
    q = quote_offer("enterprise", founder=True, phase="founder_intro", branches=6)
    assert q.extra_branches == 1
    assert q.branch_unit_cents == 2500
    assert q.total_cents == 37500
    assert (
        quote_offer(
            "enterprise", founder=True, phase="founder_intro", branches=7
        ).total_cents
        == 40000
    )
    assert (
        quote_offer(
            "enterprise", founder=True, phase="founder_ongoing", branches=5
        ).total_cents
        == 40000
    )
    assert (
        quote_offer(
            "enterprise", founder=True, phase="founder_ongoing", branches=6
        ).total_cents
        == 42500
    )


@pytest.mark.parametrize("count", [True, False, 0, -1, 4.0, "5", 10001])
def test_invalid_branch_counts_rejected(count):
    with pytest.raises(ValueError):
        quote_offer("enterprise", branches=count)


def test_portfolio_and_phase_cannot_reinterpret_input():
    with pytest.raises(ValueError):
        quote_offer("core", branches=5)
    with pytest.raises(ValueError):
        quote_offer("core", founder=True)
    with pytest.raises(ValueError):
        quote_offer("automation", phase="founder_intro")
