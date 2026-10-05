from __future__ import annotations

from decimal import Decimal
from typing import Any

from apps.assessments.snapshots import verify_snapshot
from apps.inventory.provenance import (
    CALCULATED,
    CATALOG_DERIVED,
    DECLARED,
    OBSERVED,
    UNKNOWN,
)

from .models import Report

REPORT_TITLE = "AI Risk & ROI Assessment"
REPORT_CONTEXT_VERSION = "AL-REPORT-CONTEXT-2"
RISK_BANDS = ("Low", "Moderate", "High", "Critical")


class ReportContextError(ValueError):
    pass


def _money_from_cents(value: int) -> str:
    return f"{Decimal(value) / Decimal(100):.2f}"


def _require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ReportContextError(f"{name} must be an object")
    return value


def _legacy_inventory_provenance(item):
    source_type = item.get("source_type")
    fields = {
        key: DECLARED if source_type != "discovered" else UNKNOWN
        for key in item
        if key not in {"id", "provenance"}
    }
    fields["product_id"] = CATALOG_DERIVED if item.get("product_id") else UNKNOWN
    fields["source_type"] = OBSERVED if source_type == "discovered" else DECLARED
    if source_type == "discovered":
        fields["display_name"] = CATALOG_DERIVED
        fields["vendor_name"] = CATALOG_DERIVED
    return fields


def _report_evidence(inputs):
    evidence = inputs.get("evidence_references", [])
    if not isinstance(evidence, list):
        raise ReportContextError("Evidence references must be an array")
    result = []
    for reference in evidence:
        reference = _require_mapping(reference, "evidence reference")
        result.append(
            {
                **reference,
                "provenance": reference.get("provenance", DECLARED),
            }
        )
    return result


def _report_assumptions(roi_inputs):
    assumptions = _require_mapping(roi_inputs.get("assumptions"), "ROI assumptions")
    result = {}
    for name, assumption in assumptions.items():
        assumption = _require_mapping(assumption, "ROI assumption")
        original = assumption.get("provenance")
        result[name] = {
            **assumption,
            "provenance_class": UNKNOWN if original == UNKNOWN else DECLARED,
        }
    return result


def build_report_context(report: Report) -> dict[str, Any]:
    snapshot = report.assessment_snapshot
    if snapshot.organization_id != report.organization_id:
        raise ReportContextError("Report and assessment tenant identities differ")
    if not verify_snapshot(snapshot):
        raise ReportContextError("Assessment snapshot hash verification failed")

    inputs = _require_mapping(snapshot.input_payload, "snapshot input")
    results = _require_mapping(
        snapshot.result_payload,
        "snapshot result",
    )
    inventory = inputs.get("inventory")
    inventory_results = results.get("inventory_results")
    if not isinstance(inventory, list) or not isinstance(
        inventory_results,
        list,
    ):
        raise ReportContextError("Assessment inventory material is incomplete")

    result_by_item_id = {
        result.get("inventory_item_id"): result
        for result in inventory_results
        if isinstance(result, dict)
    }
    if len(result_by_item_id) != len(inventory_results) or set(result_by_item_id) != {
        item.get("id") for item in inventory if isinstance(item, dict)
    }:
        raise ReportContextError("Assessment inventory results do not match inventory")

    tools = []
    policy_findings = []
    recommendations = []
    seen_recommendations = set()
    risk_counts = dict.fromkeys(RISK_BANDS, 0)
    highest_risk = None
    total_monthly_cost_cents = 0
    unknown_monthly_cost_count = 0

    for item in inventory:
        item = _require_mapping(item, "inventory item")
        result = _require_mapping(
            result_by_item_id[item["id"]],
            "inventory result",
        )
        risk = _require_mapping(result.get("risk"), "risk result")
        band = risk.get("band")
        score = risk.get("score")
        if band not in risk_counts or not isinstance(score, int):
            raise ReportContextError("Risk result is incomplete")
        risk_counts[band] += 1
        provenance = item.get("provenance")
        if provenance is None:
            provenance = _legacy_inventory_provenance(item)
        provenance = _require_mapping(provenance, "inventory provenance")
        monthly_cost_cents = int(item.get("monthly_cost_cents", 0))
        monthly_cost_provenance = provenance.get("monthly_cost_cents", UNKNOWN)
        if monthly_cost_provenance == UNKNOWN:
            unknown_monthly_cost_count += 1
        else:
            total_monthly_cost_cents += monthly_cost_cents
        if highest_risk is None or score > highest_risk["score"]:
            highest_risk = {
                "score": score,
                "band": band,
                "tool_name": item.get("display_name", "Unnamed tool"),
            }

        tool = {
            **item,
            "provenance": provenance,
            "monthly_cost": _money_from_cents(monthly_cost_cents),
            "monthly_cost_display": (
                UNKNOWN
                if monthly_cost_provenance == UNKNOWN
                else f"${_money_from_cents(monthly_cost_cents)}"
            ),
            "risk": {**risk, "provenance": risk.get("provenance", CALCULATED)},
        }
        tools.append(tool)

        policy_results = result.get("policy_results")
        if not isinstance(policy_results, list):
            raise ReportContextError("Policy results are incomplete")
        for finding in policy_results:
            finding = _require_mapping(finding, "policy finding")
            if finding.get("result") not in {"FAIL", "WARNING"}:
                continue
            rendered = {
                **finding,
                "inventory_item_id": item["id"],
                "tool_name": item.get("display_name", "Unnamed tool"),
            }
            policy_findings.append(rendered)
            remediation = finding.get("recommended_remediation")
            recommendation_key = (item["id"], remediation)
            if remediation and recommendation_key not in seen_recommendations:
                recommendations.append(
                    {
                        "tool_name": rendered["tool_name"],
                        "remediation": remediation,
                        "severity": finding.get("severity"),
                    }
                )
                seen_recommendations.add(recommendation_key)

    roi_inputs = _require_mapping(inputs.get("roi"), "ROI input")
    roi_result = _require_mapping(results.get("roi"), "ROI result")
    rulesets = _require_mapping(inputs.get("rulesets"), "rulesets")
    risk_configuration = _require_mapping(
        inputs.get("risk_configuration"),
        "risk configuration",
    )
    engine_versions = _require_mapping(
        inputs.get("engine_versions"),
        "engine versions",
    )
    known_spend = _money_from_cents(total_monthly_cost_cents)
    monthly_spend_display = f"${known_spend} known"
    if unknown_monthly_cost_count:
        monthly_spend_display += (
            f" + {unknown_monthly_cost_count} unknown tool"
            f"{'s' if unknown_monthly_cost_count != 1 else ''}"
        )
    report_assumptions = _report_assumptions(roi_inputs)

    return {
        "context_version": REPORT_CONTEXT_VERSION,
        "title": REPORT_TITLE,
        "metadata": {
            "report_identifier": report.report_identifier,
            "organization_display_name": (report.organization_display_name),
            "assessment_date": inputs.get("captured_at"),
            "assessment_id": str(snapshot.assessment_id),
            "assessment_version": snapshot.version,
            "assessment_snapshot_id": str(snapshot.id),
            "input_sha256": snapshot.input_sha256,
            "result_sha256": snapshot.result_sha256,
        },
        "executive_summary": {
            "inventory_count": len(tools),
            "highest_individual_risk": highest_risk,
            "monthly_spend": known_spend,
            "monthly_spend_display": monthly_spend_display,
            "unknown_monthly_cost_count": unknown_monthly_cost_count,
            "monthly_net_value": roi_result.get("monthly_net_value"),
            "finding_count": len(policy_findings),
        },
        "inventory": tools,
        "risk_overview": {
            "highest_individual_risk": highest_risk,
            "counts_by_band": risk_counts,
        },
        "individual_risk_findings": [
            {"inventory_item_id": tool["id"], **tool["risk"]} for tool in tools
        ],
        "policy_findings": policy_findings,
        "recommendations": recommendations,
        "ai_expenditure": {
            "monthly_total": known_spend,
            "monthly_total_display": monthly_spend_display,
            "unknown_monthly_cost_count": unknown_monthly_cost_count,
            "items": [
                {
                    "tool_name": tool["display_name"],
                    "monthly_cost": tool["monthly_cost"],
                    "monthly_cost_display": tool["monthly_cost_display"],
                    "provenance": tool["provenance"].get("monthly_cost_cents", UNKNOWN),
                }
                for tool in tools
            ],
        },
        "roi": {
            "assessed_item_id": roi_inputs.get("assessed_item_id"),
            "assumptions": report_assumptions,
            "result": {**roi_result, "provenance": CALCULATED},
        },
        "methodology": {
            "summary": (
                "Deterministic policy, risk, and ROI engines evaluated "
                "the immutable assessment snapshot. No language model "
                "determined assessment results."
            ),
            "snapshot_schema_version": inputs.get("snapshot_schema_version"),
            "report_context_version": REPORT_CONTEXT_VERSION,
            "engine_versions": engine_versions,
            "risk_configuration": risk_configuration,
            "provenance_legend": {
                OBSERVED: "Reported directly by bounded Collector evidence.",
                DECLARED: "Provided or confirmed by a person or imported file.",
                CATALOG_DERIVED: "Exact result from versioned catalog metadata.",
                CALCULATED: "Produced by deterministic Stewardence engines.",
                UNKNOWN: "Not established by the captured evidence.",
            },
            "evidence_boundary": (
                "Installed software does not establish business use, a paid "
                "subscription, granted permissions, data access, or capabilities. "
                "Catalog capabilities are not treated as observed permissions."
            ),
        },
        "evidence": _report_evidence(inputs),
        "assessment_date": inputs.get("captured_at"),
        "ruleset_versions": rulesets,
    }
