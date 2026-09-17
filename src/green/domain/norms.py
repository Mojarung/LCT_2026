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


class Territory(StrEnum):
    """Тип территории по 369-ПП: от него зависит, допустима ли высадка вида группы III."""

    GREEN_FUND = "green_fund"  # иные территории зелёного фонда (улицы, дворы, скверы)
    PROTECTED_GREEN = "protected_green"  # особо охраняемые зелёные территории
    NATURAL = "natural"  # природные территории
    OUTSIDE_GREEN_FUND = "outside_green_fund"


class InvasiveDecision(StrEnum):
    FORBIDDEN = "forbidden"
    CONDITIONAL = "conditional"  # допускается при выполнении условия акта


class RestrictionKind(StrEnum):
    """Основания 743-ПП п. 3.6.18: какие свойства вида делают посадку в городе недопустимой."""

    FEMALE_FLUFF = "female_fluff"  # женские экземпляры тополей и других растений с пухом
    FRUIT_LITTER = "fruit_litter"  # засоряют территорию во время плодоношения
    MASS_ALLERGEN = "mass_allergen"  # массовые аллергические реакции во время цветения


@dataclass(frozen=True, slots=True)
class DistanceRule:
    """Минимальное расстояние от посадки данного типа до объекта данного класса.

    genera ограничивает правило родами растений (латинское имя рода в нижнем регистре),
    как в МГСН 1.02-02 п. 4.2.8: у теплотрасс липа и клён не ближе 2 м, берёза не ближе 3-4 м.
    Пустое множество означает правило для любого вида. min_crown_m ограничивает правило видами
    с взрослой кроной шире этого значения (743-ПП, прим. 3 к табл. 3.6.1: широкая крона не
    ближе 10 м от здания); пока вид не выбран, такое правило не применяется. traits ограничивает
    правило видами с признаком (СП 82.13330 п. 9.22: колючие растения не ближе 2 м от
    пешеходных путей) и тоже ждёт выбора вида.
    """

    rule_id: str
    object_class: ObjectClass
    planting_type: PlantingType
    min_distance_m: float
    measure_to: MeasureTo
    severity: Severity
    citation: Citation
    genera: frozenset[str] = field(default_factory=frozenset)
    min_crown_m: float | None = None
    traits: frozenset[str] = field(default_factory=frozenset)

    @property
    def is_species_specific(self) -> bool:
        return bool(self.genera or self.traits or self.min_crown_m is not None)

    def applies_to(
        self,
        planting_type: PlantingType,
        species_lat: str | None = None,
        crown_m: float | None = None,
        traits: frozenset[str] = frozenset(),
    ) -> bool:
        if self.planting_type is not planting_type:
            return False
        if self.min_crown_m is not None and (crown_m is None or crown_m <= self.min_crown_m):
            return False
        if not self.traits <= traits:
            return False
        if not self.genera:
            return True
        return species_lat is not None and genus_of(species_lat) in self.genera


@dataclass(frozen=True, slots=True)
class InvasiveSpecies:
    """Вид из перечня инвазивных растений 369-ПП (приложение 1) с номером группы.

    species_lat из одного слова означает весь род («Reynoutria ssp.» в перечне).
    """

    rule_id: str
    species_lat: str
    group: int
    citation: Citation

    def matches(self, species_lat: str) -> bool:
        listed = self.species_lat.casefold().strip()
        if " " not in listed:
            return genus_of(species_lat) == listed
        return species_lat.casefold().strip() == listed


@dataclass(frozen=True, slots=True)
class InvasiveGroupRule:
    """Порядок 369-ПП (приложение 2) для группы: где высадка запрещена, где допускается с условием.

    Территория, не названная ни в одном списке, считается запрещённой: акт запрещает высадку
    инвазивных растений в городе (п. 2.4), исключения перечислены явно.
    """

    rule_id: str
    group: int
    conditional_on: frozenset[Territory]
    condition: str
    citation: Citation

    def decision(self, territory: Territory) -> InvasiveDecision:
        if territory in self.conditional_on:
            return InvasiveDecision.CONDITIONAL
        return InvasiveDecision.FORBIDDEN


@dataclass(frozen=True, slots=True)
class SpeciesRestriction:
    """Запрет вида по его свойству, а не по названию (743-ПП п. 3.6.18)."""

    rule_id: str
    kind: RestrictionKind
    citation: Citation


type AnyRule = DistanceRule | InvasiveSpecies | InvasiveGroupRule | SpeciesRestriction


@dataclass(frozen=True, slots=True)
class RuleBook:
    """Версионируемый набор правил. fingerprint меняется при любой правке конфигурации."""

    acts: Mapping[str, Act]
    distance_rules: tuple[DistanceRule, ...]
    fingerprint: str
    invasive_species: tuple[InvasiveSpecies, ...] = ()
    invasive_groups: tuple[InvasiveGroupRule, ...] = ()
    species_restrictions: tuple[SpeciesRestriction, ...] = ()

    @property
    def all_rules(self) -> tuple[AnyRule, ...]:
        return (
            *self.distance_rules,
            *self.invasive_species,
            *self.invasive_groups,
            *self.species_restrictions,
        )

    def distance_rules_for(
        self,
        planting_type: PlantingType,
        species_lat: str | None = None,
        crown_m: float | None = None,
        traits: frozenset[str] = frozenset(),
    ) -> tuple[DistanceRule, ...]:
        return tuple(
            r
            for r in self.distance_rules
            if r.applies_to(planting_type, species_lat, crown_m, traits)
        )

    def act_of(self, citation: Citation) -> Act | None:
        return self.acts.get(citation.act_id)

    def label_of(self, act_id: str) -> str:
        act = self.acts.get(act_id)
        return act.label if act is not None else act_id

    def rule(self, rule_id: str) -> AnyRule | None:
        for rule in self.all_rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    def invasive_for(self, species_lat: str) -> InvasiveSpecies | None:
        return next((s for s in self.invasive_species if s.matches(species_lat)), None)

    def invasive_group(self, group: int) -> InvasiveGroupRule | None:
        return next((g for g in self.invasive_groups if g.group == group), None)

    def restriction(self, kind: RestrictionKind) -> SpeciesRestriction | None:
        return next((r for r in self.species_restrictions if r.kind is kind), None)


def genus_of(species_lat: str) -> str:
    """Род из латинского названия: «Tilia cordata» -> «tilia»."""
    parts = species_lat.strip().split()
    return parts[0].casefold() if parts else ""
