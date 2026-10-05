from __future__ import annotations

from apps.policies.engine import PolicyResult, RuleLayer, evaluate_policies
from apps.policies.packs.accounting import (
    ACCOUNTING_RISK_PACK_NAME,
    ACCOUNTING_RISK_PACK_V1,
    ACCOUNTING_RISK_PACK_VERSION,
)

EXPECTED_RULE_IDS = {
    "ACC-PAYROLL-EXT",
    "ACC-PAYROLL-EXT-NO-APPROVAL",
    "ACC-BANK-WRITE",
    "ACC-BANK-TRANSACTION-NO-APPROVAL",
    "ACC-TAX-EXT",
    "ACC-CLIENT-FINANCIAL-EXPORT",
    "ACC-CLIENT-EXTERNAL-COMMUNICATION",
    "ACC-AUTONOMOUS-ACCOUNTING-MODIFICATION",
    "ACC-VENDOR-REVIEW-INCOMPLETE",
    "ACC-RETENTION-UNKNOWN",
    "ACC-TRAINING-BEHAVIOR-UNKNOWN",
}


def matched_results(context):
    evaluation = evaluate_policies(ACCOUNTING_RISK_PACK_V1.rules, context)
    return {
        result.rule_id: result
        for result in evaluation.results
        if result.result is not PolicyResult.NOT_APPLICABLE
    }


def test_accounting_is_the_single_named_mvp_industry_pack():
    assert ACCOUNTING_RISK_PACK_NAME == "accounting_and_bookkeeping"
    assert ACCOUNTING_RISK_PACK_VERSION == "1.1.0"
    assert {rule.rule_id for rule in ACCOUNTING_RISK_PACK_V1.rules} == (
        EXPECTED_RULE_IDS
    )
    assert all(
        rule.layer is RuleLayer.INDUSTRY
        and rule.version == ACCOUNTING_RISK_PACK_VERSION
        for rule in ACCOUNTING_RISK_PACK_V1.rules
    )


def test_pack_covers_the_approved_accounting_risk_subjects():
    condition_values = {
        condition.value
        for rule in ACCOUNTING_RISK_PACK_V1.rules
        for condition in rule.conditions
    }

    assert {
        "payroll",
        "tax_records",
        "banking",
        "financial_transaction",
        "record_modification",
        "financial_records",
        "data_export",
        "communication",
        "external_transfer",
        "complete",
        "unknown",
        3,
    } <= condition_values
    assert any(
        condition.field == "human_approval"
        for rule in ACCOUNTING_RISK_PACK_V1.rules
        for condition in rule.conditions
    )
    assert any(
        condition.field == "retention_status"
        for rule in ACCOUNTING_RISK_PACK_V1.rules
        for condition in rule.conditions
    )
    assert any(
        condition.field == "training_behavior"
        for rule in ACCOUNTING_RISK_PACK_V1.rules
        for condition in rule.conditions
    )


def test_realistic_bookkeeping_inventory_produces_clear_findings():
    payroll_assistant = {
        "vendor_name": "Example Payroll Assistant",
        "data_categories": ["payroll", "tax_records"],
        "capabilities": ["external_transfer"],
        "connected_systems": ["payroll"],
        "permissions": ["read"],
        "autonomy_level": 2,
        "human_approval": False,
        "vendor_review_status": "incomplete",
        "retention_status": "unknown",
        "training_behavior": "unknown",
    }

    findings = matched_results(payroll_assistant)

    assert findings["ACC-PAYROLL-EXT-NO-APPROVAL"].result is PolicyResult.FAIL
    assert findings["ACC-TAX-EXT"].result is PolicyResult.FAIL
    assert (
        findings["ACC-VENDOR-REVIEW-INCOMPLETE"].explanation
        == "The vendor review is incomplete, so the firm's review of this software "
        "is not yet documented."
    )
    assert (
        findings["ACC-RETENTION-UNKNOWN"].recommended_remediation
        == "Confirm the vendor's retention and deletion terms and record the review."
    )
    assert "customer data" in findings["ACC-TRAINING-BEHAVIOR-UNKNOWN"].explanation


def test_financial_action_and_accounting_change_findings_are_useful():
    autonomous_accounting_agent = {
        "data_categories": ["financial_records"],
        "capabilities": [
            "financial_transaction",
            "record_modification",
            "data_export",
            "communication",
        ],
        "connected_systems": ["banking", "general_ledger"],
        "permissions": ["read", "write"],
        "autonomy_level": 4,
        "human_approval": False,
        "vendor_review_status": "complete",
        "retention_status": "documented",
        "training_behavior": "not_used",
    }

    findings = matched_results(autonomous_accounting_agent)

    assert findings["ACC-BANK-WRITE"].result is PolicyResult.WARNING
    assert findings["ACC-BANK-TRANSACTION-NO-APPROVAL"].result is PolicyResult.FAIL
    assert findings["ACC-AUTONOMOUS-ACCOUNTING-MODIFICATION"].severity.name == "HIGH"
    assert (
        "who may export"
        in findings["ACC-CLIENT-FINANCIAL-EXPORT"].recommended_remediation
    )
    assert (
        "recipient"
        in findings["ACC-CLIENT-EXTERNAL-COMMUNICATION"].recommended_remediation
    )


def test_pack_does_not_claim_third_party_enforcement():
    text = " ".join(
        part
        for rule in ACCOUNTING_RISK_PACK_V1.rules
        for part in (
            rule.explanation,
            rule.remediation,
            *(effect.message or "" for effect in rule.effects),
        )
    ).lower()

    assert "unverified vendor" not in text
    assert "vendor review is incomplete" in text
    assert all(
        forbidden not in text
        for forbidden in (
            "agentledger blocked",
            "agentledger enforced",
            "agentledger prevented",
            "was blocked",
            "was stopped",
            "intercepted",
        )
    )


def test_accounting_pack_evaluation_is_repeatable():
    context = {
        "data_categories": ["payroll"],
        "capabilities": ["external_transfer"],
        "connected_systems": [],
        "permissions": [],
        "autonomy_level": 1,
        "human_approval": True,
        "vendor_review_status": "complete",
        "retention_status": "documented",
        "training_behavior": "not_used",
    }

    first = evaluate_policies(ACCOUNTING_RISK_PACK_V1.rules, context)
    second = evaluate_policies(ACCOUNTING_RISK_PACK_V1.rules, context)

    assert first == second
