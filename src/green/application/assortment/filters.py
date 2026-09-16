"""Жёсткие фильтры: какие виды в этой точке запрещены и по какому основанию.

Основание у каждой причины своего рода: norm - акт и пункт (запрет вида, отступ по роду,
крона, охранная зона ВЛ, пух у жилья), reference - справочник (морозостойкость, реагенты),
parameter - заданный ассортимент участка. Смешивать их нельзя: рекомендация справочника,
поданная как норма, - это ложная ссылка на акт в объяснении.

Проверки идут по возрастанию цены и обрываются на первом отказе: причина отказа нужна одна,
а положительные причины, найденные до неё, остаются - по ним видно, что вид успел пройти.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from green.application.assortment.context import nearest_clearance
from green.application.explain import OBJECT_LABELS, citation_text
from green.domain.norms import Severity
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from green.application.assortment.context import SiteContext
    from green.application.params import PlanParams
    from green.domain.norms import DistanceRule, PlantingType, RuleBook
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
_PP743_CLAUSE = "п. 3.6.18"
_SALT_PROOF = 2
# Набор правил зависит только от рода, типа посадки и содержимого rulebook, поэтому
# кешируется по отпечатку конфигурации: иначе 44 правила перебираются заново для каждой
# пары «посадка - вид», а пар десятки тысяч.
_RULES_CACHE: dict[tuple[str, str, str], tuple[DistanceRule, ...]] = {}
_CACHE_LIMIT = 512


@dataclass(frozen=True, slots=True)
class Reason:
    kind: str
    text: str
    rule_id: str = ""
    source: str = ""


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
    for check in (_given, _banned, _distances, _overhead, _fluff, _hardiness, _salt):
        blocking = check(species, ctx, rulebook, params, reasons)
        if blocking is not None:
            return SpeciesVerdict(species=species, allowed=False, reasons=(*reasons, blocking))
    if species.pilot_streets:
        reasons.append(Reason(PILOT, f"применён в {species.pilot_streets} паспортах пилота"))
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


def _banned(
    species: Species,
    _ctx: SiteContext,
    rulebook: RuleBook,
    _params: PlanParams,
    _reasons: list[Reason],
) -> Reason | None:
    if (ban := rulebook.ban_for(species.name_lat)) is not None:
        return Reason(
            NORM,
            f"{species.name_ru} - инвазивный вид, посадка запрещена",
            rule_id=ban.rule_id,
            source=citation_text(ban, rulebook),
        )
    if species.invasive_group is not None:
        return Reason(
            REFERENCE,
            f"{species.name_ru} отнесён к инвазивным (группа {species.invasive_group}), "
            "правила запрета в базе нет",
            source=species.sources.get("invasive_group", "369-ПП"),
        )
    return None


def _distances(
    species: Species,
    ctx: SiteContext,
    rulebook: RuleBook,
    params: PlanParams,
    reasons: list[Reason],
) -> Reason | None:
    """Отступы, зависящие от вида: правила по роду и увеличение по диаметру кроны."""
    extra = max(0.0, species.crown_mature_m - _CROWN_BASE_M) * params.crown_extra_per_m
    for rule in _forbid_rules(rulebook, params.planting_type, species):
        measured = ctx.clearance_m.get(rule.object_class)
        if measured is None:
            continue
        grows = extra > 0 and _TABLE_91 in rule.citation.clause
        threshold = rule.min_distance_m + (extra if grows else 0.0)
        target = OBJECT_LABELS.get(rule.object_class, rule.object_class.value)
        if measured + _EPS_M < threshold:
            return _too_close(species, rule, rulebook, measured, threshold)
        if rule.genera:
            reasons.append(
                Reason(
                    NORM,
                    f"до {target} {measured:.1f} м при норме {threshold:.1f} м "
                    f"для рода {species.genus.capitalize()}",
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


def _fluff(
    species: Species,
    ctx: SiteContext,
    rulebook: RuleBook,
    params: PlanParams,
    _reasons: list[Reason],
) -> Reason | None:
    housing = ctx.clearance_m.get(ObjectClass.BUILDING)
    if not species.fluff or housing is None or housing >= params.housing_zone_m:
        return None
    return Reason(
        NORM,
        f"вид даёт пух, до жилой застройки {housing:.1f} м "
        f"при защитной полосе {params.housing_zone_m:.0f} м",
        source=f"{rulebook.label_of('PP743')}, {_PP743_CLAUSE}",
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
            f"вид не переносит реагенты, до проезжей части {salt:.1f} м "
            f"при полосе засоления {params.salt_zone_m:.0f} м",
            source=source,
        )
    if species.salt_tolerance >= _SALT_PROOF:
        reasons.append(
            Reason(REFERENCE, f"солеустойчив при {salt:.1f} м до проезжей части", source=source)
        )
    return None


def _too_close(
    species: Species, rule: DistanceRule, rulebook: RuleBook, measured: float, threshold: float
) -> Reason:
    target = OBJECT_LABELS.get(rule.object_class, rule.object_class.value)
    if threshold > rule.min_distance_m:  # порог подняла крона шире 5 м
        text = (
            f"крона {species.crown_mature_m:.0f} м больше {_CROWN_BASE_M:.0f} м: отступ до "
            f"{target} увеличен с {rule.min_distance_m:.1f} до {threshold:.1f} м, "
            f"измерено {measured:.1f} м (величина увеличения - проектный параметр)"
        )
    elif rule.genera:
        text = (
            f"до {target} {measured:.1f} м при норме {threshold:.1f} м "
            f"для рода {species.genus.capitalize()}"
        )
    else:
        text = f"до {target} {measured:.1f} м при норме {threshold:.1f} м"
    return Reason(NORM, text, rule_id=rule.rule_id, source=citation_text(rule, rulebook))


def _forbid_rules(
    rulebook: RuleBook, planting_type: PlantingType, species: Species
) -> tuple[DistanceRule, ...]:
    """Правила-запреты для рода вида. Согласования (needs_approval) учтены в вердикте точки."""
    key = (rulebook.fingerprint, planting_type.value, species.genus)
    cached = _RULES_CACHE.get(key)
    if cached is None:
        if len(_RULES_CACHE) > _CACHE_LIMIT:
            _RULES_CACHE.clear()
        cached = tuple(
            rule
            for rule in rulebook.distance_rules_for(planting_type, species.name_lat)
            if rule.severity is Severity.FORBID
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
