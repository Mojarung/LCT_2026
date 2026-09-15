"""Нормы как данные: акты, цитаты и правила с устойчивыми идентификаторами."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    short: str = ""

    @property
    def label(self) -> str:
        """Короткое имя акта для объяснений: «СП 42.13330.2016», «743-ПП»."""
        return self.short or self.act_id


@dataclass(frozen=True, slots=True)
class Reference:
    """Дополнительная ссылка на пункт другого акта с тем же требованием."""

    act_id: str
    clause: str


@dataclass(frozen=True, slots=True)
class Citation:
    act_id: str
    clause: str
    quote: str
    status: CitationStatus
    related: tuple[Reference, ...] = ()

    @property
    def is_verified(self) -> bool:
        return self.status is CitationStatus.VERIFIED

    @property
    def act_ids(self) -> tuple[str, ...]:
        return (self.act_id, *(ref.act_id for ref in self.related))


@dataclass(frozen=True, slots=True)
class DistanceRule:
    """Минимальное расстояние от посадки данного типа до объекта данного класса.

    genera ограничивает правило родами растений (латинское имя рода в нижнем регистре),
    как в МГСН 1.02-02 п. 4.2.8: у теплотрасс липа и клён не ближе 2 м, берёза не ближе 3-4 м.
    Пустое множество означает правило для любого вида.
    """

    rule_id: str
    object_class: ObjectClass
    planting_type: PlantingType
    min_distance_m: float
    measure_to: MeasureTo
    severity: Severity
    citation: Citation
    genera: frozenset[str] = field(default_factory=frozenset)

    def applies_to(self, planting_type: PlantingType, species_lat: str | None = None) -> bool:
        if self.planting_type is not planting_type:
            return False
        if not self.genera:
            return True
        return species_lat is not None and genus_of(species_lat) in self.genera


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

    def distance_rules_for(
        self, planting_type: PlantingType, species_lat: str | None = None
    ) -> tuple[DistanceRule, ...]:
        return tuple(r for r in self.distance_rules if r.applies_to(planting_type, species_lat))

    def act_of(self, citation: Citation) -> Act | None:
        return self.acts.get(citation.act_id)

    def label_of(self, act_id: str) -> str:
        act = self.acts.get(act_id)
        return act.label if act is not None else act_id

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


def genus_of(species_lat: str) -> str:
    """Род из латинского названия: «Tilia cordata» -> «tilia»."""
    parts = species_lat.strip().split()
    return parts[0].casefold() if parts else ""
