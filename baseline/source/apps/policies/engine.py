from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Any

ENGINE_VERSION = "AL-POLICY-1"

SUPPORTED_OPERATORS = frozenset(
    {
        "equals",
        "not_equals",
        "contains",
        "not_contains",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
        "is_true",
        "is_false",
        "is_empty",
        "is_not_empty",
    }
)

SUPPORTED_EFFECTS = frozenset(
    {
        "risk_points",
        "severity_floor",
        "require_control",
        "create_finding",
        "recommend_review",
    }
)

SUPPORTED_RISK_DIMENSIONS = frozenset(
    {
        "data_sensitivity",
        "system_privilege",
        "external_connectivity",
        "autonomy",
        "financial_impact",
        "human_oversight",
        "vendor_risk",
        "regulatory_relevance",
    }
)

ALLOWED_CONTEXT_FIELDS = frozenset(
    {
        "autonomy_level",
        "business_owner",
        "catalog_product_id",
        "capabilities",
        "connected_systems",
        "data_categories",
        "department",
        "human_approval",
        "monthly_cost_cents",
        "permissions",
        "retention_status",
        "seat_count",
        "status",
        "training_behavior",
        "user_count",
        "vendor_name",
        "vendor_review_status",
    }
)


class PolicyDefinitionError(ValueError):
    pass


class PolicyEvaluationError(ValueError):
    pass


class RuleLayer(IntEnum):
    MANDATORY_PLATFORM = 1
    INDUSTRY = 2
    ORGANIZATION = 3
    PLATFORM_RECOMMENDATION = 4


class PolicyResult(str, Enum):
    PASS = "PASS"  # noqa: S105 - policy result, not a credential
    FAIL = "FAIL"
    WARNING = "WARNING"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Severity(IntEnum):
    NONE = 0
    LOW = 1
    MODERATE = 2
    HIGH = 3
    CRITICAL = 4


def _is_immutable_definition_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, tuple):
        return all(_is_immutable_definition_value(item) for item in value)
    if isinstance(value, frozenset):
        return all(_is_immutable_definition_value(item) for item in value)
    return False


@dataclass(frozen=True)
class Condition:
    field: str
    operator: str
    value: Any = None

    def __post_init__(self):
        if self.field not in ALLOWED_CONTEXT_FIELDS:
            raise PolicyDefinitionError(f"Unsupported policy field: {self.field}")
        if self.operator not in SUPPORTED_OPERATORS:
            raise PolicyDefinitionError(f"Unsupported policy operator: {self.operator}")
        if not _is_immutable_definition_value(self.value):
            raise PolicyDefinitionError(
                "Policy condition values must be deeply immutable"
            )
        if self.operator in {"is_true", "is_false", "is_empty", "is_not_empty"}:
            if self.value is not None:
                raise PolicyDefinitionError(
                    f"{self.operator} does not accept a comparison value"
                )


@dataclass(frozen=True)
class Effect:
    type: str
    dimension: str | None = None
    value: int | str | None = None
    control: str | None = None
    message: str | None = None

    def __post_init__(self):
        if self.type not in SUPPORTED_EFFECTS:
            raise PolicyDefinitionError(f"Unsupported policy effect: {self.type}")
        if self.type == "risk_points" and (
            not isinstance(self.value, int) or isinstance(self.value, bool)
        ):
            raise PolicyDefinitionError("risk_points requires an integer value")
        if self.type == "risk_points" and self.dimension not in (
            SUPPORTED_RISK_DIMENSIONS
        ):
            raise PolicyDefinitionError("risk_points requires a supported dimension")
        if self.type == "severity_floor" and self.value not in {
            "LOW",
            "MODERATE",
            "HIGH",
            "CRITICAL",
        }:
            raise PolicyDefinitionError("severity_floor requires a named severity")
        if self.type == "require_control" and not self.control:
            raise PolicyDefinitionError("require_control requires a control name")
        if self.type in {"create_finding", "recommend_review"} and not self.message:
            raise PolicyDefinitionError(
                f"{self.type} requires a plain-language message"
            )


@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: str
    layer: RuleLayer
    conditions: tuple[Condition, ...]
    effects: tuple[Effect, ...]
    result_on_match: PolicyResult
    explanation: str
    severity: Severity
    remediation: str
    overridable: bool = False

    def __post_init__(self):
        if not self.rule_id or not self.version:
            raise PolicyDefinitionError("A rule ID and version are required")
        if not isinstance(self.layer, RuleLayer):
            raise PolicyDefinitionError("A rule requires a recognized precedence layer")
        if not isinstance(self.conditions, tuple) or not all(
            isinstance(condition, Condition) for condition in self.conditions
        ):
            raise PolicyDefinitionError("Rule conditions must be an immutable tuple")
        if not isinstance(self.effects, tuple) or not all(
            isinstance(effect, Effect) for effect in self.effects
        ):
            raise PolicyDefinitionError("Rule effects must be an immutable tuple")
        if not isinstance(self.result_on_match, PolicyResult):
            raise PolicyDefinitionError("A rule requires a recognized result")
        if not isinstance(self.severity, Severity):
            raise PolicyDefinitionError("A rule requires a recognized severity")
        if not self.conditions:
            raise PolicyDefinitionError("A rule requires at least one condition")
        if not self.explanation or not self.remediation:
            raise PolicyDefinitionError("Explanation and remediation are required")


@dataclass(frozen=True)
class RuleEvaluation:
    rule_id: str
    rule_version: str
    evidence: tuple[tuple[str, Any], ...]
    result: PolicyResult
    explanation: str
    severity: Severity
    recommended_remediation: str
    effects: tuple[Effect, ...]


@dataclass(frozen=True)
class PolicyEvaluation:
    engine_version: str
    results: tuple[RuleEvaluation, ...]


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == () or value == [] or value == {}


def _ordered_comparison(actual: Any, expected: Any, operator: str) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        raise PolicyEvaluationError("Boolean values cannot use ordered comparisons")
    if not isinstance(actual, type(expected)) or not isinstance(
        actual, (int, float, str)
    ):
        raise PolicyEvaluationError(
            "Ordered comparison values must have matching types"
        )
    operations = {
        "greater_than": actual > expected,
        "greater_than_or_equal": actual >= expected,
        "less_than": actual < expected,
        "less_than_or_equal": actual <= expected,
    }
    return operations[operator]


def evaluate_condition(condition: Condition, context: dict[str, Any]) -> bool:
    actual = context.get(condition.field)
    operator = condition.operator
    if operator == "equals":
        return actual == condition.value
    if operator == "not_equals":
        return actual != condition.value
    if operator in {"contains", "not_contains"}:
        if not isinstance(actual, (str, list, tuple, set, frozenset)):
            raise PolicyEvaluationError("contains requires text or a collection")
        contains = condition.value in actual
        return contains if operator == "contains" else not contains
    if operator in {
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
    }:
        return _ordered_comparison(actual, condition.value, operator)
    if operator == "is_true":
        return actual is True
    if operator == "is_false":
        return actual is False
    if operator == "is_empty":
        return _is_empty(actual)
    if operator == "is_not_empty":
        return not _is_empty(actual)
    raise PolicyEvaluationError("Unsupported policy operator")


def evaluate_rule(rule: Rule, context: dict[str, Any]) -> RuleEvaluation:
    evidence = tuple(
        (condition.field, context.get(condition.field)) for condition in rule.conditions
    )
    matched = all(
        evaluate_condition(condition, context) for condition in rule.conditions
    )
    return RuleEvaluation(
        rule_id=rule.rule_id,
        rule_version=rule.version,
        evidence=evidence,
        result=rule.result_on_match if matched else PolicyResult.NOT_APPLICABLE,
        explanation=rule.explanation,
        severity=rule.severity if matched else Severity.NONE,
        recommended_remediation=rule.remediation,
        effects=rule.effects if matched else (),
    )


def evaluate_policies(
    rules: tuple[Rule, ...],
    context: dict[str, Any],
) -> PolicyEvaluation:
    ordered_rules = sorted(
        rules, key=lambda rule: (rule.layer, rule.rule_id, rule.version)
    )
    return PolicyEvaluation(
        engine_version=ENGINE_VERSION,
        results=tuple(evaluate_rule(rule, context) for rule in ordered_rules),
    )
