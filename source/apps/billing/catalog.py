from __future__ import annotations

FOUNDER_LIMIT = 20

PORTFOLIOS = {
    "core": {
        "name": "Core",
        "audience": "Freelancer",
        "standard_cents": 9900,
        "founder_intro_cents": 4900,
        "founder_intro_months": 6,
        "founder_ongoing_cents": 7500,
        "available": True,
        "label": "Available now",
        "description": (
            "Deterministic AI inventory, risk assessment, ROI modeling, "
            "evidence-backed findings, Collector workflows, and decision-ready reports."
        ),
    },
    "automation": {
        "name": "Automation",
        "audience": "Organization",
        "standard_cents": 14900,
        "founder_intro_cents": 7500,
        "founder_intro_months": 6,
        "founder_ongoing_cents": 11200,
        "available": False,
        "label": "Coming next",
        "description": (
            "Everything in Core plus governed automated detection, persistent "
            "assessment workflows, and qualified automation capabilities."
        ),
    },
    "enterprise": {
        "name": "Enterprise",
        "audience": "Corporate",
        "standard_cents": 50000,
        "included_branches": 4,
        "founder_included_branches": 5,
        "extra_branch_cents": 2500,
        "founder_intro_cents": 35000,
        "founder_intro_months": 6,
        "founder_ongoing_cents": 40000,
        "available": False,
        "label": "In development",
        "description": (
            "Organization-scale stewardship with employee subaccounts, persistent "
            "listeners, advanced risk signals, financial integrations, document "
            "intelligence, audit support, and authorized action flows."
        ),
    },
}
