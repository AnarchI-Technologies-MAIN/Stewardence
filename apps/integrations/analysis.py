"""Period-specific ROI from explicitly attributed evidence; no guessed savings."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from enum import StrEnum
from hashlib import sha256

import rfc8785


class EvidenceKind(StrEnum):
    MEASURED = "measured"
    CUSTOMER_SUPPLIED = "customer_supplied"
    ESTIMATED = "estimated"


@dataclass(frozen=True)
class Evidence:
    reference: str
    source_account: str
    metric: str
    value: Decimal
    unit: str
    period_start: date
    period_end: date
    kind: EvidenceKind
    source_sha256: str

    def __post_init__(self):
        if not self.reference or not self.source_account:
            raise ValueError("Evidence needs a source record and account")
        if (
            not isinstance(self.value, Decimal)
            or not self.value.is_finite()
            or self.value < 0
        ):
            raise ValueError("Evidence values must be finite, nonnegative Decimals")
        if (
            self.value > Decimal("1000000000000000")
            or not -8 <= self.value.as_tuple().exponent <= 15
        ):
            raise ValueError("Evidence exceeds supported magnitude or precision")
        if type(self.period_start) is not date or type(self.period_end) is not date:
            raise ValueError("Periods must use calendar dates")
        if self.period_end <= self.period_start:
            raise ValueError("Evidence period must be nonempty and end-exclusive")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("Evidence needs a SHA256 source fingerprint")
        if not isinstance(self.kind, EvidenceKind):
            raise ValueError("Evidence provenance must be explicit")


@dataclass(frozen=True)
class Attribution:
    workflow_id: str
    approved_by: str
    approval_reference: str
    currency: str
    period_start: date
    period_end: date

    def __post_init__(self):
        if not all((self.workflow_id, self.approved_by, self.approval_reference)):
            raise ValueError("Workflow attribution requires recorded customer approval")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("Use an explicit currency code")
        if type(self.period_start) is not date or type(self.period_end) is not date:
            raise ValueError("Periods must use calendar dates")
        if self.period_end <= self.period_start:
            raise ValueError("Attribution period must be nonempty")


# These amounts cover one approved comparison period. Do not infer a monthly
# recurrence from a bank charge or extrapolate realized savings from revenue.
REQUIRED = {
    "tool_cost": "currency",
    "implementation_cost": "currency",
    "baseline_hours": "hours",
    "current_hours": "hours",
    "loaded_hourly_rate": "currency/hour",
}
OPTIONAL = {"attributable_revenue": "currency", "avoided_cost": "currency"}


def _card(code, title, explanation, references, workflow_id):
    return {
        "code": code,
        "title": title,
        "explanation": explanation,
        "workflow_id": workflow_id,
        "evidence_references": sorted(references),
        "approval_required": True,
        "execution_status": "proposal_only",
    }


def analyze_roi(attribution: Attribution, evidence: tuple[Evidence, ...]) -> dict:
    with localcontext(Context(prec=60, rounding=ROUND_HALF_UP)):
        result = _analyze_roi(attribution, evidence)
        source_material = {
            "approval": {
                "workflow_id": attribution.workflow_id,
                "approved_by": attribution.approved_by,
                "reference": attribution.approval_reference,
                "currency": attribution.currency,
                "start": attribution.period_start.isoformat(),
                "end": attribution.period_end.isoformat(),
            },
            "evidence": sorted(
                {
                    rfc8785.dumps(
                        {
                            "reference": e.reference,
                            "source_account": e.source_account,
                            "metric": e.metric,
                            "value": str(e.value),
                            "unit": e.unit,
                            "start": e.period_start.isoformat(),
                            "end": e.period_end.isoformat(),
                            "kind": e.kind.value,
                            "source_sha256": e.source_sha256,
                        }
                    ).decode()
                    for e in evidence
                }
            ),
        }
        result["calculation_rule_version"] = "stewardence.integration-roi.v1"
        result["input_sha256"] = sha256(rfc8785.dumps(source_material)).hexdigest()
        result["result_sha256"] = sha256(rfc8785.dumps(result)).hexdigest()
        return result


def _analyze_roi(attribution: Attribution, evidence: tuple[Evidence, ...]) -> dict:
    metrics = {}
    identities = {}
    for item in evidence:
        key = (item.source_account, item.reference, item.metric)
        previous = identities.get(key)
        if previous is not None:
            if previous != item:
                raise ValueError("Conflicting duplicate source evidence")
            continue
        identities[key] = item
        if item.metric not in REQUIRED | OPTIONAL:
            raise ValueError("Unsupported ROI metric")
        if (item.period_start, item.period_end) != (
            attribution.period_start,
            attribution.period_end,
        ):
            raise ValueError("ROI evidence must cover the approved comparison period")
        expected = (REQUIRED | OPTIONAL)[item.metric].replace(
            "currency", attribution.currency
        )
        if item.unit != expected:
            raise ValueError("Mixed currency or incompatible evidence units")
        # Require a reviewed period aggregate per metric. Summing invoices,
        # payments, and bank lines together would count the same spend twice.
        if item.metric in metrics:
            raise ValueError(
                "Multiple aggregates for the same metric need reconciliation"
            )
        metrics[item.metric] = item
    references = [item.reference for item in identities.values()]
    missing = sorted(REQUIRED.keys() - metrics.keys())
    common = {
        "schema_version": 1,
        "workflow_id": attribution.workflow_id,
        "currency": attribution.currency,
        "period_start": attribution.period_start.isoformat(),
        "period_end_exclusive": attribution.period_end.isoformat(),
        "attribution_approval_reference": attribution.approval_reference,
        "evidence_references": sorted(references),
        "assumptions": sorted(
            k for k, v in metrics.items() if v.kind != EvidenceKind.MEASURED
        ),
        "excluded_optional_benefits": sorted(OPTIONAL.keys() - metrics.keys()),
        "causal_claim": (
            "customer-approved attribution; not independently established causality"
        ),
    }
    if missing:
        return {
            **common,
            "status": "insufficient_evidence",
            "missing_metrics": missing,
            "roi_percent": None,
            "net_value": None,
            "action_cards": [
                _card(
                    "complete_roi_evidence",
                    "Complete ROI evidence",
                    "Provide the missing inputs: " + ", ".join(missing),
                    references,
                    attribution.workflow_id,
                )
            ],
        }

    def value(name):
        return metrics[name].value if name in metrics else Decimal(0)

    hours_difference = value("baseline_hours") - value("current_hours")
    labor_value = hours_difference * value("loaded_hourly_rate")
    benefit = labor_value + value("attributable_revenue") + value("avoided_cost")
    cost = value("tool_cost") + value("implementation_cost")
    net = benefit - cost

    def quantize(number):
        return str(number.quantize(Decimal("0.01")))

    modeled = bool(common["assumptions"])
    cards = []
    if net < 0:
        cards.append(
            _card(
                "review_negative_roi",
                "Review workflow economics",
                "Attributed benefits are below recorded costs for this period. "
                "Review the inputs and workflow before deciding whether "
                "to change or cancel a tool.",
                references,
                attribution.workflow_id,
            )
        )
    if modeled:
        cards.append(
            _card(
                "validate_roi_assumptions",
                "Validate ROI assumptions",
                "Replace estimated or customer-supplied inputs with measurements "
                "where feasible.",
                references,
                attribution.workflow_id,
            )
        )
    if cost == 0:
        cards.append(
            _card(
                "verify_zero_cost",
                "Verify zero recorded cost",
                "ROI percentage is undefined when the comparison-period cost is zero.",
                references,
                attribution.workflow_id,
            )
        )
    return {
        **common,
        "status": "modeled" if modeled else "measured_inputs",
        "missing_metrics": [],
        "hours_difference": str(hours_difference),
        "labor_value": quantize(labor_value),
        "total_benefit": quantize(benefit),
        "total_cost": quantize(cost),
        "net_value": quantize(net),
        "roi_percent": quantize(net / cost * 100) if cost else None,
        "action_cards": cards,
    }
