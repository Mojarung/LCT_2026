"""План посадок: принятые посадки, отказы и трасса проверенных правил."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from green.domain.norms import PlantingType
    from green.domain.objects import ObjectClass, SourceRef


class Verdict(StrEnum):
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"
    NEEDS_APPROVAL = "needs_approval"
    UNKNOWN = "unknown"


class CheckOutcome(StrEnum):
    PASS = "pass"  # noqa: S105 - исход проверки, не пароль
    FAIL = "fail"
    NO_DATA = "no_data"


@dataclass(frozen=True, slots=True)
class Species:
    code: str
    name_ru: str
    name_lat: str
    crown_diameter_m: float


@dataclass(frozen=True, slots=True)
class RuleCheck:
    """Результат проверки одного правила для одной точки."""

    rule_id: str
    outcome: CheckOutcome
    threshold_m: float | None = None
    measured_m: float | None = None
    nearest: SourceRef | None = None
    object_class: ObjectClass | None = None


@dataclass(frozen=True, slots=True)
class Placement:
    placement_id: str
    number: int
    planting_type: PlantingType
    species: Species
    x: float
    y: float
    verdict: Verdict
    checks: tuple[RuleCheck, ...]
    notes: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class Rejection:
    rejection_id: str
    number: int
    planting_type: PlantingType
    x: float
    y: float
    verdict: Verdict
    blocking: tuple[RuleCheck, ...]


@dataclass(frozen=True, slots=True)
class Explanation:
    """Человекочитаемое объяснение решения, собранное только из трассы правил."""

    subject_id: str
    number: int
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class Plan:
    placements: tuple[Placement, ...]
    rejections: tuple[Rejection, ...]
    explanations: tuple[Explanation, ...] = field(default=())
    warnings: tuple[str, ...] = field(default=())

    @property
    def allowed_count(self) -> int:
        return sum(1 for p in self.placements if p.verdict is Verdict.ALLOWED)

    @property
    def approval_count(self) -> int:
        return sum(1 for p in self.placements if p.verdict is Verdict.NEEDS_APPROVAL)
