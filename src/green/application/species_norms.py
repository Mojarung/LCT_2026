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
PLUS, LIMITED, MINUS = "plus", "limited", "minus"
CATEGORY_LABELS = {
    "parks": "сады и парки",
    "squares": "скверы и бульвары",
    "streets": "улицы и дороги",
    "yards": "внутриквартальные",
    "special": "специальные",
}
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


@dataclass(frozen=True, slots=True)
class _Site:
    """Что известно об участке целиком: тип территории (369-ПП) и категория насаждений (МГСН)."""

    territory: Territory
    category: str
    act_over_allergen: bool = True


def species_norms(
    species: Species,
    rulebook: RuleBook,
    territory: str,
    category: str = "streets",
    *,
    allergen_act_priority: bool = True,
) -> SpeciesNorms:
    site = _Site(Territory(territory), category, act_over_allergen=allergen_act_priority)
    reasons: list[Reason] = []
    for check in (_invasive, _category, _female_fluff, _fruit_litter, _mass_allergen):
        blocking = check(species, rulebook, site, reasons)
        if blocking is not None:
            return SpeciesNorms(blocking=blocking, reasons=tuple(reasons))
    return SpeciesNorms(blocking=None, reasons=tuple(reasons))


def _invasive(
    species: Species, rulebook: RuleBook, site: _Site, reasons: list[Reason]
) -> Reason | None:
    territory = site.territory
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


def _category(
    species: Species, rulebook: RuleBook, site: _Site, reasons: list[Reason]
) -> Reason | None:
    """МГСН 1.02-02, табл. В.6: «-» - вид для категории не рекомендован, «с огр.» - с оговоркой."""
    mark = species.categories.get(site.category)
    if mark is None:
        return None
    label = CATEGORY_LABELS.get(site.category, site.category)
    basis = species.sources.get("categories", "МГСН 1.02-02, табл. В.6")
    rule = rulebook.restriction(RestrictionKind.PLANTING_CATEGORY)
    source = citation_text(rule, rulebook) if rule else basis
    rule_id = rule.rule_id if rule else ""
    if mark == MINUS:
        return Reason(
            NORM,
            f"вид не рекомендован для категории насаждений «{label}» ({basis})",
            rule_id=rule_id,
            source=source,
        )
    limited = " с ограничением" if mark == LIMITED else ""
    reasons.append(
        Reason(
            NORM,
            f"вид рекомендован{limited} для категории «{label}» ({basis})",
            rule_id=rule_id,
            source=source,
        )
    )
    return None


def _female_fluff(
    species: Species, rulebook: RuleBook, _site: _Site, reasons: list[Reason]
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
    species: Species, rulebook: RuleBook, _site: _Site, _reasons: list[Reason]
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
    species: Species, rulebook: RuleBook, site: _Site, reasons: list[Reason]
) -> Reason | None:
    """Пункт 3.6.18 видов не называет, отнесение к массовым аллергенам справочное.

    МГСН 1.02-02 (табл. В.6) и 515-ПП берёзу рекомендуют, заказчик считает акты
    непротиворечивыми (docs/notes/15-organizers-qa.md, вопросы 7 и 17). Поэтому вид, который
    московский акт называет для категории участка, допускается, и основание говорит, какой
    акт решил; аллергенность снижает оценку. Параметр профиля allergen_act_priority=false
    ставит запрет п. 3.6.18 выше: вопрос про берёзу заказчику задан (там же, раздел 5).
    """
    if species.allergen < _MASS_ALLERGEN:
        return None
    categories = species.sources.get("categories", "МГСН 1.02-02, табл. В.6")
    allergen = species.sources.get("allergen", "справочник")
    recommended = species.categories.get(site.category) in {PLUS, LIMITED}
    if recommended and site.act_over_allergen:
        # Две короткие строки вместо одной длинной: факт и чем он разрешён.
        reasons.append(Reason(REFERENCE, "пыльца - сильный аллерген", source=allergen))
        reasons.append(
            Reason(
                REFERENCE,
                f"{_PP743_3618} видов не называет, {categories} вид рекомендует: решает акт, "
                "называющий вид",
                source=categories,
            )
        )
        return None
    also = f"; {categories} вид рекомендует, но запрет строже" if recommended else ""
    return _restricted(
        rulebook,
        RestrictionKind.MASS_ALLERGEN,
        f"{species.name_ru} вызывает массовые аллергические реакции во время цветения{also}",
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
