"""Нормы как данные: акты, цитаты и правила с устойчивыми идентификаторами."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import date

    from green.domain.objects import ObjectClass


class CitationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    NOT_FOUND = "not_found"


class PlantingType(StrEnum):
    TREE = "tree"
    SHRUB = "shrub"
    HEDGE = "hedge"
    LAWN = "lawn"


class Severity(StrEnum):
    """Последствие нарушения правила для кандидата в посадку."""

    FORBID = "forbid"
    NEEDS_APPROVAL = "needs_approval"


class MeasureTo(StrEnum):
    """До какого элемента объекта мерится расстояние от оси ствола или центра куста."""

    AXIS = "axis"
    OUTER_WALL = "outer_wall"
    EDGE = "edge"
    UNSPECIFIED = "unspecified"


@dataclass(frozen=True, slots=True)
class Act:
    act_id: str
    title: str
    edition: str
    url: str
    checked_at: date | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    act_id: str
    clause: str
    quote: str
    status: CitationStatus

    @property
    def is_verified(self) -> bool:
        return self.status is CitationStatus.VERIFIED


@dataclass(frozen=True, slots=True)
class DistanceRule:
    """Минимальное расстояние от посадки данного типа до объекта данного класса."""

    rule_id: str
    object_class: ObjectClass
    planting_type: PlantingType
    min_distance_m: float
    measure_to: MeasureTo
    severity: Severity
    citation: Citation

    def applies_to(self, planting_type: PlantingType) -> bool:
        return self.planting_type is planting_type


@dataclass(frozen=True, slots=True)
class SpeciesBan:
    """Запрет вида в ассортименте (например, инвазивные виды)."""

    rule_id: str
    species_lat: str
    citation: Citation


@dataclass(frozen=True, slots=True)
class RuleBook:
    """Версионируемый набор правил. fingerprint меняется при любой правке конфигурации."""

    acts: Mapping[str, Act]
    distance_rules: tuple[DistanceRule, ...]
    species_bans: tuple[SpeciesBan, ...]
    fingerprint: str

    def distance_rules_for(self, planting_type: PlantingType) -> tuple[DistanceRule, ...]:
        return tuple(rule for rule in self.distance_rules if rule.applies_to(planting_type))

    def act_of(self, citation: Citation) -> Act | None:
        return self.acts.get(citation.act_id)

    def rule(self, rule_id: str) -> DistanceRule | SpeciesBan | None:
        for rule in (*self.distance_rules, *self.species_bans):
            if rule.rule_id == rule_id:
                return rule
        return None

    def ban_for(self, species_lat: str) -> SpeciesBan | None:
        normalized = species_lat.casefold().strip()
        for ban in self.species_bans:
            if ban.species_lat.casefold() == normalized:
                return ban
        return None
