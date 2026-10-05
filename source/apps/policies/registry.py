from __future__ import annotations

from dataclasses import dataclass

from .engine import Rule


class PublishedRuleConflict(ValueError):
    pass


@dataclass(frozen=True)
class PublishedRuleSet:
    name: str
    version: str
    rules: tuple[Rule, ...]

    def __post_init__(self):
        if not self.name or not self.version or not self.rules:
            raise ValueError("Published rule sets require a name, version, and rules")
        if not isinstance(self.rules, tuple) or not all(
            isinstance(rule, Rule) for rule in self.rules
        ):
            raise ValueError("Published rule sets require an immutable tuple of rules")


class PublishedRuleRegistry:
    def __init__(self):
        self._published: dict[tuple[str, str], PublishedRuleSet] = {}

    def publish(self, ruleset: PublishedRuleSet) -> None:
        key = (ruleset.name, ruleset.version)
        if key in self._published:
            raise PublishedRuleConflict(
                "A published rule-set version cannot be replaced or mutated"
            )
        self._published[key] = ruleset

    def get(self, name: str, version: str) -> PublishedRuleSet:
        return self._published[(name, version)]
