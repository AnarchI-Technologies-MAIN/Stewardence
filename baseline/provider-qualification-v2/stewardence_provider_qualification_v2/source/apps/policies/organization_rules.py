from __future__ import annotations

from typing import Any

from .engine import (
    Condition,
    Effect,
    PolicyDefinitionError,
    PolicyResult,
    Rule,
    RuleLayer,
    Severity,
)

DEFINITION_KEYS = frozenset({"all", "effects"})
CONDITION_KEYS = frozenset({"field", "operator", "value"})
EFFECT_KEYS = frozenset({"type", "dimension", "value", "control", "message"})


def compile_organization_rule(record) -> Rule:
    definition = record.definition
    if not isinstance(definition, dict) or set(definition) != DEFINITION_KEYS:
        raise PolicyDefinitionError("Organization rule definition has unsupported keys")
    raw_conditions = definition["all"]
    raw_effects = definition["effects"]
    if not isinstance(raw_conditions, list) or not isinstance(raw_effects, list):
        raise PolicyDefinitionError("Organization rule sections must be lists")

    conditions = []
    for value in raw_conditions:
        if not isinstance(value, dict) or set(value) != CONDITION_KEYS:
            raise PolicyDefinitionError("Organization rule condition is invalid")
        conditions.append(Condition(**value))

    effects = []
    for value in raw_effects:
        if not isinstance(value, dict) or not set(value) <= EFFECT_KEYS:
            raise PolicyDefinitionError("Organization rule effect is invalid")
        effects.append(Effect(**value))

    return Rule(
        rule_id=f"ORG-{record.id}",
        version=str(record.version),
        layer=RuleLayer.ORGANIZATION,
        conditions=tuple(conditions),
        effects=tuple(effects),
        result_on_match=PolicyResult(record.result_on_match),
        explanation=record.explanation,
        severity=Severity[record.severity],
        remediation=record.remediation,
    )


def organization_rule_snapshot(record) -> dict[str, Any]:
    compile_organization_rule(record)
    return {
        "id": str(record.id),
        "name": record.name,
        "version": record.version,
        "definition": record.definition,
        "result_on_match": record.result_on_match,
        "severity": record.severity,
        "explanation": record.explanation,
        "remediation": record.remediation,
        "source_type": record.source_type,
        "generation_fingerprint": record.generation_fingerprint or None,
        "source_inventory_item_id": (
            str(record.source_inventory_item_id)
            if record.source_inventory_item_id
            else None
        ),
        "detector_id": record.detector_id or None,
        "detector_version": record.detector_version or None,
        "mapping_id": record.mapping_id or None,
        "mapping_version": record.mapping_version or None,
    }
