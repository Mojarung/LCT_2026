"""Нормы, которые решают судьбу вида целиком, независимо от точки: 369-ПП и 743-ПП п. 3.6.18.

369-ПП: перечень (приложение 1) даёт группу вида, порядок (приложение 2) по группе и типу
территории решает, запрещена высадка или допускается с условием. 743-ПП п. 3.6.18 запрещает
в городе женские экземпляры тополей и другие растения, засоряющие территорию при
плодоношении или вызывающие массовую аллергию при цветении. Сам пункт видов не называет,
поэтому отнесение вида к этим группам берётся из каталога с источником, и объяснение
показывает обе части: норму и основание отнесения.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from green.application.explain import citation_text
from green.domain.norms import InvasiveDecision, RestrictionKind, Territory
from green.domain.planting import Reason

if TYPE_CHECKING:
    from green.domain.norms import AnyRule, RuleBook
    from green.domain.planting import Species

NORM = "norm"
REFERENCE = "reference"
MALE = "male"
_MASS_ALLERGEN = 2
_PP743_3618 = "743-ПП, п. 3.6.18"
_ROMAN = {1: "I", 2: "II", 3: "III", 4: "IV"}
TERRITORY_LABELS = {
    Territory.GREEN_FUND: "иная территория зелёного фонда",
    Territory.PROTECTED_GREEN: "особо охраняемая зелёная территория",
    Territory.NATURAL: "природная территория",
    Territory.OUTSIDE_GREEN_FUND: "территория вне зелёного фонда",
}


@dataclass(frozen=True, slots=True)
class SpeciesNorms:
    """Итог видовых норм: причина запрета (или None) и основания, которые вид прошёл."""

    blocking: Reason | None
    reasons: tuple[Reason, ...]


def species_norms(species: Species, rulebook: RuleBook, territory: str) -> SpeciesNorms:
    reasons: list[Reason] = []
    for check in (_invasive, _female_fluff, _fruit_litter, _mass_allergen):
        blocking = check(species, rulebook, Territory(territory), reasons)
        if blocking is not None:
            return SpeciesNorms(blocking=blocking, reasons=tuple(reasons))
    return SpeciesNorms(blocking=None, reasons=tuple(reasons))


def _invasive(
    species: Species, rulebook: RuleBook, territory: Territory, reasons: list[Reason]
) -> Reason | None:
    listed = rulebook.invasive_for(species.name_lat)
    if listed is None:
        if species.invasive_group is None:
            return None
        # Каталог и rules.yaml расходятся: тест каталога это ловит, здесь - fail-closed.
        return Reason(
            REFERENCE,
            f"{species.name_ru} отмечен в каталоге как инвазивный (группа "
            f"{species.invasive_group}), но в перечне правил его нет",
            source=species.sources.get("invasive_group", "каталог"),
        )
    group = rulebook.invasive_group(listed.group)
    roman = _ROMAN.get(listed.group, str(listed.group))
    place = TERRITORY_LABELS.get(territory, territory.value)
    if group is None or group.decision(territory) is InvasiveDecision.FORBIDDEN:
        return Reason(
            NORM,
            f"{species.name_ru} - инвазивный вид группы {roman}, высадка не допускается "
            f"(тип территории: {place})",
            rule_id=listed.rule_id,
            source=_sources(rulebook, listed, group),
        )
    reasons.append(
        Reason(
            NORM,
            f"{species.name_ru} - инвазивный вид группы {roman}: на территории типа «{place}» "
            "высадка допускается с условием",
            rule_id=group.rule_id,
            source=_sources(rulebook, listed, group),
            condition=group.condition,
        )
    )
    return None


def _female_fluff(
    species: Species, rulebook: RuleBook, _territory: Territory, reasons: list[Reason]
) -> Reason | None:
    if not species.fluff:
        return None
    basis = species.sources.get("fluff", "каталог")
    if species.planting_sex == MALE:
        reasons.append(
            _restricted(
                rulebook,
                RestrictionKind.FEMALE_FLUFF,
                f"{species.name_ru}: в посадку идут только мужские экземпляры, пуха они не дают",
                basis=species.sources.get("planting_sex", basis),
                condition="посадочный материал - только мужские клоны",
            )
        )
        return None
    return _restricted(
        rulebook,
        RestrictionKind.FEMALE_FLUFF,
        f"{species.name_ru}: женские экземпляры дают пух, мужской клон в каталоге не указан",
        basis=basis,
    )


def _fruit_litter(
    species: Species, rulebook: RuleBook, _territory: Territory, _reasons: list[Reason]
) -> Reason | None:
    if not species.fruit_litter:
        return None
    return _restricted(
        rulebook,
        RestrictionKind.FRUIT_LITTER,
        f"{species.name_ru} засоряет территорию во время плодоношения",
        basis=species.sources.get("fruit_litter", "каталог"),
    )


def _mass_allergen(
    species: Species, rulebook: RuleBook, _territory: Territory, _reasons: list[Reason]
) -> Reason | None:
    if species.allergen < _MASS_ALLERGEN:
        return None
    return _restricted(
        rulebook,
        RestrictionKind.MASS_ALLERGEN,
        f"{species.name_ru} вызывает массовые аллергические реакции во время цветения",
        basis=species.sources.get("allergen", "каталог"),
    )


def _restricted(
    rulebook: RuleBook,
    kind: RestrictionKind,
    text: str,
    *,
    basis: str,
    condition: str = "",
) -> Reason:
    rule = rulebook.restriction(kind)
    source = citation_text(rule, rulebook) if rule else f"{_PP743_3618} (правила нет в базе)"
    return Reason(
        NORM,
        f"{text} (отнесение вида: {basis})",
        rule_id=rule.rule_id if rule else "",
        source=source,
        condition=condition,
    )


def _sources(rulebook: RuleBook, *rules: AnyRule | None) -> str:
    return "; ".join(citation_text(rule, rulebook) for rule in rules if rule is not None)
