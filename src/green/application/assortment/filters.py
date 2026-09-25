"""Жёсткие фильтры: какие виды в этой точке запрещены и по какому основанию.

Основание у каждой причины своего рода: norm - акт и пункт (369-ПП, 743-ПП п. 3.6.18, отступ
по роду, крона, охранная зона ВЛ), reference - справочник (морозостойкость, реагенты),
parameter - заданный ассортимент участка. Смешивать их нельзя: рекомендация справочника,
поданная как норма, - это ложная ссылка на акт в объяснении.

Проверки идут по возрастанию цены и обрываются на первом отказе: причина отказа нужна одна,
а положительные причины, найденные до неё, остаются - по ним видно, что вид успел пройти.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from green.application.assortment.context import nearest_clearance
from green.application.barriers import BARRIER_CONDITION, barrier_distance
from green.application.explain import OBJECT_LABELS, citation_text
from green.application.species_norms import species_norms
from green.application.wording import decimal, plural
from green.domain.norms import PlantingType, RestrictionKind, Severity
from green.domain.objects import ObjectClass
from green.domain.planting import Reason

if TYPE_CHECKING:
    from green.application.assortment.context import SiteContext
    from green.application.params import PlanParams
    from green.domain.norms import DistanceRule, RuleBook
    from green.domain.planting import Species

NORM = "norm"
REFERENCE = "reference"
PILOT = "pilot"
COMPOSITION = "composition"
PARAMETER = "parameter"

_EPS_M = 1e-6
_CROWN_BASE_M = 5.0  # прим. к табл. 9.1: расстояния даны для кроны не более 5 м
_TABLE_91 = "табл. 9.1"
_SALT_CLASSES = (ObjectClass.ROAD, ObjectClass.CURB)
_SALT_PROOF = 2
_TRAIT_LABELS = {"thorny": "колючее", "toxic": "токсичное"}
_RELEVANT_FACTOR = 3.0  # во сколько норм укладывается расстояние, при котором правило значимо
# Набор правил зависит только от рода, кроны, типа посадки и содержимого rulebook, поэтому
# кешируется по отпечатку конфигурации: иначе 44 правила перебираются заново для каждой
# пары «посадка - вид», а пар десятки тысяч.
_RULES_CACHE: dict[tuple[object, ...], tuple[DistanceRule, ...]] = {}
_CACHE_LIMIT = 512


@dataclass(frozen=True, slots=True)
class SpeciesVerdict:
    species: Species
    allowed: bool
    reasons: tuple[Reason, ...]

    @property
    def blocking(self) -> Reason | None:
        """Причина отказа: последняя в списке, остальные - то, что вид успел пройти."""
        return None if self.allowed else self.reasons[-1]


def species_verdict(
    species: Species, ctx: SiteContext, rulebook: RuleBook, params: PlanParams
) -> SpeciesVerdict:
    reasons: list[Reason] = []
    for check in (_given, _species_norms, _distances, _overhead, _hardiness, _salt):
        blocking = check(species, ctx, rulebook, params, reasons)
        if blocking is not None:
            return SpeciesVerdict(species=species, allowed=False, reasons=(*reasons, blocking))
    if species.pilot_streets:
        passports = plural(species.pilot_streets, "паспорте", "паспортах", "паспортах")
        reasons.append(Reason(PILOT, f"применён в {species.pilot_streets} {passports} пилота"))
    return SpeciesVerdict(species=species, allowed=True, reasons=tuple(reasons))


def _given(
    species: Species,
    _ctx: SiteContext,
    _rulebook: RuleBook,
    params: PlanParams,
    _reasons: list[Reason],
) -> Reason | None:
    if params.assortment_mode == "given" and species.code not in params.given_assortment:
        return Reason(PARAMETER, "вида нет в заданном ассортименте участка")
    return None


def _species_norms(
    species: Species,
    _ctx: SiteContext,
    rulebook: RuleBook,
    params: PlanParams,
    reasons: list[Reason],
) -> Reason | None:
    """369-ПП и 743-ПП п. 3.6.18: запрет или условие для вида, одинаковые в любой точке."""
    verdict = species_norms(
        species,
        rulebook,
        params.territory,
        params.planting_category,
        allergen_act_priority=params.allergen_act_priority,
    )
    reasons.extend(verdict.reasons)
    return verdict.blocking


def _distances(
    species: Species,
    ctx: SiteContext,
    rulebook: RuleBook,
    params: PlanParams,
    reasons: list[Reason],
) -> Reason | None:
    """Отступы, зависящие от вида: правила по роду, по ширине кроны и увеличение по кроне."""
    extra = max(0.0, species.crown_mature_m - _CROWN_BASE_M) * params.crown_extra_per_m
    for rule in _forbid_rules(rulebook, params.planting_type, species, params.disabled_rules):
        measured = ctx.clearance_m.get(rule.object_class)
        if measured is None:
            continue
        grows = (
            extra > 0
            and _TABLE_91 in rule.citation.clause
            and (
                not params.crown_extra_classes
                or rule.object_class.value in params.crown_extra_classes
            )
        )
        threshold = rule.min_distance_m + (extra if grows else 0.0)
        target = OBJECT_LABELS.get(rule.object_class, rule.object_class.value)
        if measured + _EPS_M < threshold:
            relaxed = _with_barrier(species, rule, rulebook, measured, params)
            if relaxed is None:
                return _too_close(species, rule, rulebook, measured, threshold)
            reasons.append(relaxed)
            continue
        # «До теплосети 30 м при норме 4 м» - не основание выбрать вид, а шум: правило по
        # роду попадает в объяснение, только когда объект рядом и норма действительно решала.
        if rule.is_species_specific and measured <= threshold * _RELEVANT_FACTOR:
            reasons.append(
                Reason(
                    NORM,
                    f"до {target} {decimal(measured)} м при норме {decimal(threshold)} м "
                    f"{_rule_scope(species, rule)}",
                    rule_id=rule.rule_id,
                    source=citation_text(rule, rulebook),
                )
            )
    return None


def _overhead(
    species: Species,
    ctx: SiteContext,
    rulebook: RuleBook,
    params: PlanParams,
    _reasons: list[Reason],
) -> Reason | None:
    if not ctx.under_overhead_line or species.height_m <= params.max_height_under_lines_m:
        return None
    rule = _rule_for(rulebook, params.planting_type, ObjectClass.POWER_LINE_OVERHEAD)
    return Reason(
        NORM,
        f"точка в охранной зоне воздушной линии: высота вида {species.height_m:.0f} м "
        f"больше предельных {params.max_height_under_lines_m:.0f} м "
        "(предел - проектный параметр)",
        rule_id=rule.rule_id if rule else "",
        source=citation_text(rule, rulebook) if rule else "",
    )


def _hardiness(
    species: Species,
    _ctx: SiteContext,
    _rulebook: RuleBook,
    params: PlanParams,
    _reasons: list[Reason],
) -> Reason | None:
    if species.hardiness_zone <= params.region_hardiness_zone:
        return None
    return Reason(
        REFERENCE,
        f"зона морозостойкости вида {species.hardiness_zone} выше региональной "
        f"{params.region_hardiness_zone}",
        source=species.sources.get("hardiness_zone", "справочник"),
    )


def _salt(
    species: Species,
    ctx: SiteContext,
    _rulebook: RuleBook,
    params: PlanParams,
    reasons: list[Reason],
) -> Reason | None:
    salt = nearest_clearance(ctx, _SALT_CLASSES)
    if salt is None or salt >= params.salt_zone_m:
        return None
    source = species.sources.get("salt_tolerance", "справочник")
    if species.salt_tolerance == 0:
        return Reason(
            REFERENCE,
            f"вид не переносит реагенты, до проезжей части {decimal(salt)} м "
            f"при полосе засоления {params.salt_zone_m:.0f} м",
            source=source,
        )
    if species.salt_tolerance >= _SALT_PROOF:
        reasons.append(
            Reason(
                REFERENCE, f"солеустойчив при {decimal(salt)} м до проезжей части", source=source
            )
        )
    return None


def _with_barrier(
    species: Species,
    rule: DistanceRule,
    rulebook: RuleBook,
    measured: float,
    params: PlanParams,
) -> Reason | None:
    """Ближе нормы к сети или бордюру: допустимо ли это дерево с прикорневым барьером."""
    if not params.root_barriers or not rule.object_class.is_barrier_relaxable:
        return None
    if rule.planting_type is not PlantingType.TREE:
        return None
    required = barrier_distance(species.height_m)
    if required is None or measured + _EPS_M < required:
        return None
    target = OBJECT_LABELS.get(rule.object_class, rule.object_class.value)
    basis = rulebook.restriction(RestrictionKind.ROOT_BARRIER)
    return Reason(
        NORM,
        f"до {target} {decimal(measured)} м при норме {decimal(rule.min_distance_m)} м: "
        f"допустимо с прикорневым барьером, для дерева высотой {species.height_m:.0f} м не ближе "
        f"{decimal(required)} м",
        rule_id=basis.rule_id if basis else rule.rule_id,
        source=citation_text(basis or rule, rulebook),
        condition=(
            f"{BARRIER_CONDITION} со стороны {target}, барьер не ближе 0,5 м к сети и бордюру"
        ),
    )


def _too_close(
    species: Species, rule: DistanceRule, rulebook: RuleBook, measured: float, threshold: float
) -> Reason:
    target = OBJECT_LABELS.get(rule.object_class, rule.object_class.value)
    if threshold > rule.min_distance_m:  # порог подняла крона шире 5 м
        text = (
            f"крона {species.crown_mature_m:.0f} м больше {_CROWN_BASE_M:.0f} м: отступ до "
            f"{target} увеличен с {decimal(rule.min_distance_m)} до {decimal(threshold)} м, "
            f"измерено {decimal(measured)} м (величину увеличения акт не задаёт: принят прирост "
            "радиуса кроны, толкование проекта)"
        )
    elif rule.is_species_specific:
        text = (
            f"до {target} {decimal(measured)} м при норме {decimal(threshold)} м "
            f"{_rule_scope(species, rule)}"
        )
    else:
        text = f"до {target} {decimal(measured)} м при норме {decimal(threshold)} м"
    return Reason(NORM, text, rule_id=rule.rule_id, source=citation_text(rule, rulebook))


def _forbid_rules(
    rulebook: RuleBook, planting_type: PlantingType, species: Species, disabled: tuple[str, ...]
) -> tuple[DistanceRule, ...]:
    """Правила-запреты для рода вида. Согласования (needs_approval) учтены в вердикте точки.

    Правила, отключённые профилем, не применяются и здесь: размещение их не проверяло, и
    измеренного расстояния для них в контексте точки нет.
    """
    key = (
        rulebook.fingerprint,
        planting_type.value,
        species.genus,
        species.crown_mature_m,
        species.traits,
        disabled,
    )
    cached = _RULES_CACHE.get(key)
    if cached is None:
        if len(_RULES_CACHE) > _CACHE_LIMIT:
            _RULES_CACHE.clear()
        cached = tuple(
            rule
            for rule in rulebook.distance_rules_for(
                planting_type,
                species.name_lat,
                crown_m=species.crown_mature_m,
                traits=species.traits,
            )
            if rule.severity is Severity.FORBID and rule.rule_id not in disabled
        )
        _RULES_CACHE[key] = cached
    return cached


def _rule_for(
    rulebook: RuleBook, planting_type: PlantingType, object_class: ObjectClass
) -> DistanceRule | None:
    for rule in rulebook.distance_rules_for(planting_type):
        if rule.object_class is object_class:
            return rule
    return None


def _rule_scope(species: Species, rule: DistanceRule) -> str:
    """К кому относится видозависимое правило: к роду или к виду с широкой кроной."""
    if rule.min_crown_m is not None:
        return f"для кроны шире {rule.min_crown_m:.0f} м (у вида {species.crown_mature_m:.0f} м)"
    if rule.traits:
        labels = [_TRAIT_LABELS.get(trait, trait) for trait in sorted(rule.traits)]
        return f"для растений с признаком: {', '.join(labels)}"
    return f"для рода {species.genus.capitalize()}"
