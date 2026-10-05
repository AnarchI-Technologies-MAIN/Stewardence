from __future__ import annotations

from apps.policies.engine import (
    Condition,
    Effect,
    PolicyResult,
    Rule,
    RuleLayer,
    Severity,
)
from apps.policies.registry import PublishedRuleSet

ACCOUNTING_RISK_PACK_NAME = "accounting_and_bookkeeping"
ACCOUNTING_RISK_PACK_VERSION = "1.1.0"


ACCOUNTING_RISK_PACK_V1 = PublishedRuleSet(
    name=ACCOUNTING_RISK_PACK_NAME,
    version=ACCOUNTING_RISK_PACK_VERSION,
    rules=(
        Rule(
            rule_id="ACC-PAYROLL-EXT",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(
                Condition("data_categories", "contains", "payroll"),
                Condition("capabilities", "contains", "external_transfer"),
            ),
            effects=(
                Effect("risk_points", dimension="data_sensitivity", value=25),
                Effect("require_control", control="human_approval"),
                Effect("severity_floor", value="HIGH"),
            ),
            result_on_match=PolicyResult.FAIL,
            explanation=(
                "This software can access payroll information and send information "
                "outside the firm."
            ),
            severity=Severity.HIGH,
            remediation=(
                "Document and configure a human approval step in the source system "
                "or business process before payroll information is sent."
            ),
        ),
        Rule(
            rule_id="ACC-PAYROLL-EXT-NO-APPROVAL",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(
                Condition("data_categories", "contains", "payroll"),
                Condition("capabilities", "contains", "external_transfer"),
                Condition("human_approval", "is_false"),
            ),
            effects=(Effect("severity_floor", value="CRITICAL"),),
            result_on_match=PolicyResult.FAIL,
            explanation=(
                "Payroll information can leave the firm without a recorded human "
                "approval step."
            ),
            severity=Severity.CRITICAL,
            remediation=(
                "Add an approval step in the source application or operating "
                "procedure, then record that step in AgentLedger."
            ),
        ),
        Rule(
            rule_id="ACC-BANK-WRITE",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(
                Condition("connected_systems", "contains", "banking"),
                Condition("permissions", "contains", "write"),
            ),
            effects=(
                Effect("risk_points", dimension="system_privilege", value=30),
                Effect("recommend_review", message="Review banking write access."),
                Effect("severity_floor", value="HIGH"),
            ),
            result_on_match=PolicyResult.WARNING,
            explanation=(
                "This software has permission to change information in a banking "
                "system."
            ),
            severity=Severity.HIGH,
            remediation=(
                "Confirm that banking write access is necessary and document who "
                "reviews changes."
            ),
        ),
        Rule(
            rule_id="ACC-BANK-TRANSACTION-NO-APPROVAL",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(
                Condition("connected_systems", "contains", "banking"),
                Condition("capabilities", "contains", "financial_transaction"),
                Condition("human_approval", "is_false"),
            ),
            effects=(
                Effect("risk_points", dimension="financial_impact", value=40),
                Effect("risk_points", dimension="human_oversight", value=30),
                Effect("severity_floor", value="CRITICAL"),
                Effect("require_control", control="human_approval"),
            ),
            result_on_match=PolicyResult.FAIL,
            explanation=(
                "This software can initiate financial activity without a recorded "
                "approval step."
            ),
            severity=Severity.CRITICAL,
            remediation=(
                "Require transaction approval in the banking or payment system "
                "before continued autonomous use."
            ),
        ),
        Rule(
            rule_id="ACC-TAX-EXT",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(
                Condition("data_categories", "contains", "tax_records"),
                Condition("capabilities", "contains", "external_transfer"),
            ),
            effects=(
                Effect("risk_points", dimension="data_sensitivity", value=25),
                Effect("require_control", control="human_approval"),
                Effect("severity_floor", value="HIGH"),
            ),
            result_on_match=PolicyResult.FAIL,
            explanation=("This software can send tax records outside the firm."),
            severity=Severity.HIGH,
            remediation=(
                "Document who approves tax-record transfers and how recipients are "
                "checked before information is sent."
            ),
        ),
        Rule(
            rule_id="ACC-CLIENT-FINANCIAL-EXPORT",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(
                Condition("data_categories", "contains", "financial_records"),
                Condition("capabilities", "contains", "data_export"),
            ),
            effects=(
                Effect("risk_points", dimension="data_sensitivity", value=20),
                Effect("recommend_review", message="Review client export controls."),
            ),
            result_on_match=PolicyResult.WARNING,
            explanation=("This software can export a client's financial records."),
            severity=Severity.HIGH,
            remediation=(
                "Confirm who may export client records and document how each export "
                "is reviewed and delivered."
            ),
        ),
        Rule(
            rule_id="ACC-CLIENT-EXTERNAL-COMMUNICATION",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(
                Condition("data_categories", "contains", "financial_records"),
                Condition("capabilities", "contains", "communication"),
            ),
            effects=(
                Effect("risk_points", dimension="external_connectivity", value=20),
                Effect("require_control", control="recipient_review"),
            ),
            result_on_match=PolicyResult.WARNING,
            explanation=(
                "This software can include client financial information in messages "
                "sent outside the firm."
            ),
            severity=Severity.HIGH,
            remediation=(
                "Require a person to check the recipient and message before client "
                "financial information is sent."
            ),
        ),
        Rule(
            rule_id="ACC-AUTONOMOUS-ACCOUNTING-MODIFICATION",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(
                Condition("capabilities", "contains", "record_modification"),
                Condition("autonomy_level", "greater_than_or_equal", 3),
            ),
            effects=(
                Effect("risk_points", dimension="autonomy", value=30),
                Effect("require_control", control="change_review"),
                Effect("severity_floor", value="HIGH"),
            ),
            result_on_match=PolicyResult.FAIL,
            explanation=(
                "This software can change accounting records while performing some "
                "tasks on its own."
            ),
            severity=Severity.HIGH,
            remediation=(
                "Require a person to review accounting changes and document how "
                "incorrect changes are corrected."
            ),
        ),
        Rule(
            rule_id="ACC-VENDOR-REVIEW-INCOMPLETE",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(Condition("vendor_review_status", "not_equals", "complete"),),
            effects=(
                Effect("risk_points", dimension="vendor_risk", value=15),
                Effect("recommend_review", message="Complete the vendor review."),
            ),
            result_on_match=PolicyResult.WARNING,
            explanation=(
                "The vendor review is incomplete, so the firm's review of this "
                "software is not yet documented."
            ),
            severity=Severity.MODERATE,
            remediation=(
                "Complete and record the vendor review, including data handling, "
                "security, and contract terms."
            ),
        ),
        Rule(
            rule_id="ACC-RETENTION-UNKNOWN",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(Condition("retention_status", "equals", "unknown"),),
            effects=(
                Effect("risk_points", dimension="regulatory_relevance", value=10),
                Effect("recommend_review", message="Confirm the retention terms."),
            ),
            result_on_match=PolicyResult.WARNING,
            explanation=(
                "The firm has not recorded how long this software keeps its data."
            ),
            severity=Severity.MODERATE,
            remediation=(
                "Confirm the vendor's retention and deletion terms and record the "
                "review."
            ),
        ),
        Rule(
            rule_id="ACC-TRAINING-BEHAVIOR-UNKNOWN",
            version=ACCOUNTING_RISK_PACK_VERSION,
            layer=RuleLayer.INDUSTRY,
            conditions=(Condition("training_behavior", "equals", "unknown"),),
            effects=(
                Effect("risk_points", dimension="vendor_risk", value=10),
                Effect(
                    "recommend_review",
                    message="Confirm whether customer data is used for training.",
                ),
            ),
            result_on_match=PolicyResult.WARNING,
            explanation=(
                "The firm has not recorded whether the vendor uses customer data to "
                "train models."
            ),
            severity=Severity.MODERATE,
            remediation=(
                "Confirm the vendor's model-training terms and record whether firm "
                "or client data is used."
            ),
        ),
    ),
)
