from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError

import pytest

from apps.policies import engine
from apps.policies.engine import (
    Condition,
    Effect,
    PolicyDefinitionError,
    PolicyEvaluationError,
    PolicyResult,
    Rule,
    RuleLayer,
    Severity,
    evaluate_condition,
    evaluate_policies,
)
from apps.policies.registry import (
    PublishedRuleConflict,
    PublishedRuleRegistry,
    PublishedRuleSet,
)


def example_rule(
    rule_id="RULE-1",
    layer=RuleLayer.INDUSTRY,
    conditions=None,
):
    return Rule(
        rule_id=rule_id,
        version="1.0.0",
        layer=layer,
        conditions=conditions or (Condition("data_categories", "contains", "payroll"),),
        effects=(
            Effect("risk_points", dimension="data_sensitivity", value=25),
            Effect("require_control", control="human_approval"),
        ),
        result_on_match=PolicyResult.FAIL,
        explanation="Payroll information can leave the firm.",
        severity=Severity.HIGH,
        remediation="Require a person to approve external payroll transfers.",
    )


@pytest.mark.parametrize(
    ("operator", "actual", "expected", "result"),
    [
        ("equals", "active", "active", True),
        ("not_equals", "active", "trial", True),
        ("contains", ["payroll", "tax"], "payroll", True),
        ("not_contains", ["tax"], "payroll", True),
        ("greater_than", 4, 3, True),
        ("greater_than_or_equal", 4, 4, True),
        ("less_than", 3, 4, True),
        ("less_than_or_equal", 4, 4, True),
        ("is_true", True, None, True),
        ("is_false", False, None, True),
        ("is_empty", [], None, True),
        ("is_not_empty", ["client_information"], None, True),
    ],
)
def test_all_approved_operators(operator, actual, expected, result):
    condition = Condition("data_categories", operator, expected)
    assert evaluate_condition(condition, {"data_categories": actual}) is result


def test_rule_result_contains_required_evidence_and_explanation_fields():
    evaluation = evaluate_policies(
        (example_rule(),),
        {"data_categories": ["payroll"], "human_approval": False},
    ).results[0]

    assert evaluation.rule_id == "RULE-1"
    assert evaluation.rule_version == "1.0.0"
    assert evaluation.evidence == (("data_categories", ["payroll"]),)
    assert evaluation.result == PolicyResult.FAIL
    assert evaluation.explanation == "Payroll information can leave the firm."
    assert evaluation.severity == Severity.HIGH
    assert "approve" in evaluation.recommended_remediation
    assert {effect.type for effect in evaluation.effects} == {
        "risk_points",
        "require_control",
    }


def test_nonmatching_rule_is_not_applicable_and_has_no_effects():
    evaluation = evaluate_policies(
        (example_rule(),),
        {"data_categories": ["public_information"]},
    ).results[0]

    assert evaluation.result == PolicyResult.NOT_APPLICABLE
    assert evaluation.severity == Severity.NONE
    assert evaluation.effects == ()


def test_rule_precedence_is_exact_and_independent_of_input_order():
    rules = (
        example_rule("RECOMMENDATION", RuleLayer.PLATFORM_RECOMMENDATION),
        example_rule("ORGANIZATION", RuleLayer.ORGANIZATION),
        example_rule("MANDATORY", RuleLayer.MANDATORY_PLATFORM),
        example_rule("INDUSTRY", RuleLayer.INDUSTRY),
    )

    result = evaluate_policies(rules, {"data_categories": ["payroll"]})

    assert [evaluation.rule_id for evaluation in result.results] == [
        "MANDATORY",
        "INDUSTRY",
        "ORGANIZATION",
        "RECOMMENDATION",
    ]


def test_organization_result_cannot_erase_a_mandatory_platform_failure():
    mandatory = example_rule("MANDATORY", RuleLayer.MANDATORY_PLATFORM)
    organization = Rule(
        rule_id="ORGANIZATION",
        version="1.0.0",
        layer=RuleLayer.ORGANIZATION,
        conditions=(Condition("data_categories", "contains", "payroll"),),
        effects=(),
        result_on_match=PolicyResult.PASS,
        explanation="The organization has documented this use.",
        severity=Severity.NONE,
        remediation="Retain the documentation.",
    )

    result = evaluate_policies(
        (organization, mandatory), {"data_categories": ["payroll"]}
    )

    assert [evaluation.result for evaluation in result.results] == [
        PolicyResult.FAIL,
        PolicyResult.PASS,
    ]


def test_same_context_rules_and_engine_produce_identical_result():
    rules = (example_rule(),)
    context = {"data_categories": ["payroll"], "human_approval": False}

    first = evaluate_policies(rules, context)
    second = evaluate_policies(rules, context)

    assert first == second
    assert first.engine_version == "AL-POLICY-1"


@pytest.mark.parametrize(
    "constructor",
    [
        lambda: Condition("untrusted_field", "equals", "value"),
        lambda: Condition("status", "execute_python", "value"),
        lambda: Effect("block_software", value=True),
        lambda: Effect("risk_points", value="twenty"),
        lambda: Effect("risk_points", dimension="invented", value=20),
        lambda: Effect("severity_floor", value="EXTREME"),
        lambda: Effect("severity_floor", value="NONE"),
        lambda: Effect("require_control"),
        lambda: Effect("create_finding"),
        lambda: Effect("recommend_review"),
    ],
)
def test_unapproved_rule_structures_fail_closed(constructor):
    with pytest.raises(PolicyDefinitionError):
        constructor()


def test_ordered_comparisons_reject_type_confusion():
    with pytest.raises(PolicyEvaluationError, match="matching types"):
        evaluate_condition(
            Condition("monthly_cost_cents", "greater_than", "100"),
            {"monthly_cost_cents": 200},
        )
    with pytest.raises(PolicyEvaluationError, match="Boolean"):
        evaluate_condition(
            Condition("monthly_cost_cents", "greater_than", False),
            {"monthly_cost_cents": True},
        )


def test_published_rule_versions_are_frozen_and_cannot_be_replaced():
    ruleset = PublishedRuleSet("accounting", "1.0.0", (example_rule(),))
    registry = PublishedRuleRegistry()
    registry.publish(ruleset)

    with pytest.raises(FrozenInstanceError):
        ruleset.version = "changed"
    with pytest.raises(PublishedRuleConflict, match="cannot be replaced"):
        registry.publish(ruleset)

    next_version = PublishedRuleSet("accounting", "1.1.0", (example_rule(),))
    registry.publish(next_version)
    assert registry.get("accounting", "1.0.0") is ruleset
    assert registry.get("accounting", "1.1.0") is next_version


@pytest.mark.parametrize(
    "mutable_value",
    [["payroll"], {"category": "payroll"}, {"payroll"}],
)
def test_published_rule_definitions_reject_nested_mutability(mutable_value):
    with pytest.raises(PolicyDefinitionError, match="deeply immutable"):
        Condition("data_categories", "equals", mutable_value)


def test_rule_and_rule_set_collections_must_be_immutable_tuples():
    with pytest.raises(PolicyDefinitionError, match="immutable tuple"):
        Rule(
            rule_id="MUTABLE",
            version="1.0.0",
            layer=RuleLayer.INDUSTRY,
            conditions=[Condition("status", "equals", "active")],
            effects=(),
            result_on_match=PolicyResult.PASS,
            explanation="Mutable definitions are rejected.",
            severity=Severity.NONE,
            remediation="Use an immutable tuple.",
        )
    with pytest.raises(ValueError, match="immutable tuple"):
        PublishedRuleSet("accounting", "1.0.0", [example_rule()])


def test_engine_has_no_ambient_or_executable_authority():
    source = inspect.getsource(engine)
    tree = ast.parse(source)
    imported_roots = {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert imported_roots <= {"__future__", "dataclasses", "enum", "typing"}
    assert called_names.isdisjoint({"eval", "exec", "compile", "open"})
    assert all(
        forbidden not in source
        for forbidden in (
            "django.db",
            "requests",
            "httpx",
            "socket",
            "datetime.now",
            "time.time",
            "openai",
        )
    )
