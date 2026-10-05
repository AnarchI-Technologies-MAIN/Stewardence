from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

from .engine import SUPPORTED_RISK_DIMENSIONS, PolicyEvaluation, Severity

RISK_ENGINE_VERSION = "AL-RISK-1"


class RiskDefinitionError(ValueError):
    pass


class RiskDimension(str, Enum):
    DATA_SENSITIVITY = "data_sensitivity"
    SYSTEM_PRIVILEGE = "system_privilege"
    AUTONOMY = "autonomy"
    EXTERNAL_CONNECTIVITY = "external_connectivity"
    HUMAN_OVERSIGHT = "human_oversight"
    FINANCIAL_IMPACT = "financial_impact"
    REGULATORY_RELEVANCE = "regulatory_relevance"
    VENDOR_RISK = "vendor_risk"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()


class RiskBand(str, Enum):
    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"
    CRITICAL = "Critical"


@dataclass(frozen=True)
class RiskConfiguration:
    version: str
    weights: tuple[tuple[RiskDimension, int], ...]

    def __post_init__(self):
        if not isinstance(self.weights, tuple) or not all(
            isinstance(item, tuple) and len(item) == 2 for item in self.weights
        ):
            raise RiskDefinitionError("Risk weights must be an immutable tuple")
        configured_dimensions = tuple(dimension for dimension, _weight in self.weights)
        if set(configured_dimensions) != set(RiskDimension):
            raise RiskDefinitionError(
                "Risk weights must define each dimension exactly once"
            )
        if len(configured_dimensions) != len(set(configured_dimensions)):
            raise RiskDefinitionError("Risk dimensions cannot be repeated")
        if any(
            not isinstance(weight, int) or isinstance(weight, bool) or weight < 0
            for _dimension, weight in self.weights
        ):
            raise RiskDefinitionError("Risk weights must be nonnegative integers")
        if sum(weight for _dimension, weight in self.weights) != 100:
            raise RiskDefinitionError("Risk weights must total 100 percent")
        if not self.version:
            raise RiskDefinitionError("A risk configuration version is required")


DEFAULT_RISK_CONFIGURATION = RiskConfiguration(
    version=RISK_ENGINE_VERSION,
    weights=(
        (RiskDimension.DATA_SENSITIVITY, 20),
        (RiskDimension.SYSTEM_PRIVILEGE, 20),
        (RiskDimension.AUTONOMY, 15),
        (RiskDimension.EXTERNAL_CONNECTIVITY, 15),
        (RiskDimension.HUMAN_OVERSIGHT, 10),
        (RiskDimension.FINANCIAL_IMPACT, 10),
        (RiskDimension.REGULATORY_RELEVANCE, 5),
        (RiskDimension.VENDOR_RISK, 5),
    ),
)


@dataclass(frozen=True)
class RiskContribution:
    reason: str
    rule_id: str
    rule_version: str
    dimension: RiskDimension
    points: int

    def __post_init__(self):
        if not self.reason or not self.rule_id or not self.rule_version:
            raise RiskDefinitionError("Risk contributions require a reason and rule")
        if not isinstance(self.dimension, RiskDimension):
            raise RiskDefinitionError("Risk contributions require a known dimension")
        if not isinstance(self.points, int) or isinstance(self.points, bool):
            raise RiskDefinitionError("Risk contribution points must be integers")

    @property
    def signed_points(self) -> str:
        return f"{self.points:+d}"


@dataclass(frozen=True)
class DimensionScore:
    dimension: RiskDimension
    raw_points: int
    score: int
    weight_percent: int
    weighted_points: Decimal

    @property
    def arithmetic(self) -> str:
        return (
            f"{self.dimension.label}: {self.score} × {self.weight_percent}% "
            f"= {self.weighted_points}"
        )


@dataclass(frozen=True)
class RiskScore:
    engine_version: str
    configuration_version: str
    dimensions: tuple[DimensionScore, ...]
    contributions: tuple[RiskContribution, ...]
    raw_weighted_score: Decimal
    score: int
    band: RiskBand
    severity_floor: RiskBand | None

    @property
    def explanation_lines(self) -> tuple[str, ...]:
        return tuple(
            f"{contribution.signed_points} {contribution.reason} "
            f"({contribution.rule_id} v{contribution.rule_version})"
            for contribution in self.contributions
        )


BAND_MINIMUMS = (
    (RiskBand.LOW, 0),
    (RiskBand.MODERATE, 25),
    (RiskBand.HIGH, 50),
    (RiskBand.CRITICAL, 75),
)


def _band_minimum(band: RiskBand) -> int:
    return next(minimum for candidate, minimum in BAND_MINIMUMS if candidate is band)


def classify_risk(score: int) -> RiskBand:
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        raise RiskDefinitionError("Overall risk score must be an integer from 0 to 100")
    if score <= 24:
        return RiskBand.LOW
    if score <= 49:
        return RiskBand.MODERATE
    if score <= 74:
        return RiskBand.HIGH
    return RiskBand.CRITICAL


def calculate_risk(
    contributions: tuple[RiskContribution, ...],
    severity_floors: tuple[RiskBand, ...] = (),
    configuration: RiskConfiguration = DEFAULT_RISK_CONFIGURATION,
) -> RiskScore:
    if not isinstance(contributions, tuple) or not all(
        isinstance(contribution, RiskContribution) for contribution in contributions
    ):
        raise RiskDefinitionError("Risk contributions must be an immutable tuple")
    if not isinstance(severity_floors, tuple) or not all(
        isinstance(floor, RiskBand) for floor in severity_floors
    ):
        raise RiskDefinitionError("Severity floors must be an immutable tuple")

    breakdowns = []
    for dimension, weight in configuration.weights:
        raw_points = sum(
            contribution.points
            for contribution in contributions
            if contribution.dimension is dimension
        )
        dimension_score = min(100, max(0, raw_points))
        weighted_points = Decimal(dimension_score) * Decimal(weight) / Decimal(100)
        breakdowns.append(
            DimensionScore(
                dimension=dimension,
                raw_points=raw_points,
                score=dimension_score,
                weight_percent=weight,
                weighted_points=weighted_points,
            )
        )

    raw_weighted_score = sum(
        (breakdown.weighted_points for breakdown in breakdowns), start=Decimal(0)
    )
    rounded_score = int(raw_weighted_score.quantize(Decimal("1"), ROUND_HALF_UP))
    severity_floor = max(
        severity_floors,
        key=_band_minimum,
        default=None,
    )
    score = max(
        rounded_score,
        _band_minimum(severity_floor) if severity_floor is not None else 0,
    )

    return RiskScore(
        engine_version=RISK_ENGINE_VERSION,
        configuration_version=configuration.version,
        dimensions=tuple(breakdowns),
        contributions=contributions,
        raw_weighted_score=raw_weighted_score,
        score=score,
        band=classify_risk(score),
        severity_floor=severity_floor,
    )


def calculate_policy_risk(
    evaluation: PolicyEvaluation,
    configuration: RiskConfiguration = DEFAULT_RISK_CONFIGURATION,
) -> RiskScore:
    contributions = []
    floors = []
    for result in evaluation.results:
        for effect in result.effects:
            if effect.type == "risk_points":
                if effect.dimension not in SUPPORTED_RISK_DIMENSIONS:
                    raise RiskDefinitionError("Policy used an unknown risk dimension")
                contributions.append(
                    RiskContribution(
                        reason=result.explanation,
                        rule_id=result.rule_id,
                        rule_version=result.rule_version,
                        dimension=RiskDimension(effect.dimension),
                        points=int(effect.value),
                    )
                )
            elif effect.type == "severity_floor":
                floors.append(RiskBand[Severity[effect.value].name])

    return calculate_risk(tuple(contributions), tuple(floors), configuration)
