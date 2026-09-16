"""Оценка пригодности вида к точке: взвешенная сумма факторов, каждый в [0, 1].

Разнообразие в оценку не входит - оно ограничение назначения (assign.py). Иначе «этого
вида уже много» смешивается с «вид плохо подходит месту», и альтернативы в объяснении
становятся несравнимыми: проценты у двух видов зависели бы от порядка обхода.

Веса берутся из профиля целиком: словарь в профиле заменяет набор по умолчанию, а не
дополняет его, поэтому фактор, не названный в профиле, получает нулевой вес.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from green.application.assortment.context import nearest_clearance
from green.application.assortment.structures import GROUP, ROW, SINGLE
from green.application.params import DEFAULT_WEIGHTS
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Mapping

    from green.application.assortment.context import SiteContext
    from green.application.params import PlanParams
    from green.domain.planting import Species

_SALT_CLASSES = (ObjectClass.ROAD, ObjectClass.CURB)
_MAX_SCALE = 2.0  # шкалы устойчивости и аллергенности: 0-2
_MONTHS = 12
_EVERGREEN_BONUS = 0.25
_REFERENCE_LIFESPAN_YEARS = 150.0
_PILOT_STREETS = 7.0  # улиц в пилоте, по которым есть паспорта
_CARE = {1: 1.0, 2: 0.5, 3: 0.0}
_USE_BY_KIND = {ROW: "row", GROUP: "group", SINGLE: "solitaire"}


@dataclass(frozen=True, slots=True)
class Score:
    total: float  # 0..1
    factors: Mapping[str, float]


def score_species(species: Species, ctx: SiteContext, params: PlanParams) -> Score:
    factors = {
        "site": _site(species, ctx, params),
        "function": _function(species, ctx),
        "decor": _decor(species),
        "longevity": min(1.0, species.lifespan_years / _REFERENCE_LIFESPAN_YEARS),
        "care": _CARE.get(species.care_level, 0.0),
        "pilot": min(1.0, species.pilot_streets / _PILOT_STREETS),
    }
    weights = params.assortment_weights or DEFAULT_WEIGHTS
    total_weight = sum(max(0.0, weights.get(name, 0.0)) for name in factors)
    if total_weight <= 0:
        return Score(total=0.0, factors=factors)
    weighted = sum(max(0.0, weights.get(name, 0.0)) * value for name, value in factors.items())
    return Score(total=weighted / total_weight, factors=factors)


def percent(score: Score) -> int:
    return round(100 * score.total)


def _site(species: Species, ctx: SiteContext, params: PlanParams) -> float:
    """Сколько условий места вид выдерживает: уплотнение всегда, реагенты и газ - у дороги."""
    parts = [species.compaction_tolerance / _MAX_SCALE]
    salt = nearest_clearance(ctx, _SALT_CLASSES)
    if salt is not None and salt < params.salt_zone_m:
        parts.append(species.salt_tolerance / _MAX_SCALE)
        parts.append(species.gas_tolerance / _MAX_SCALE)
    housing = ctx.clearance_m.get(ObjectClass.BUILDING)
    if housing is not None and housing < params.housing_zone_m:
        # Аллергенность не запрещена ни одним актом, поэтому она снижает оценку, а не
        # отсеивает вид: у жилья это отличает берёзу от липы, не выдавая себя за норму.
        parts.append(1.0 - species.allergen / _MAX_SCALE)
    return sum(parts) / len(parts)


def _function(species: Species, ctx: SiteContext) -> float:
    parts = []
    use = _USE_BY_KIND.get(ctx.structure_kind or "")
    if use is not None:
        parts.append(1.0 if use in species.uses else 0.0)
    if ctx.under_overhead_line:
        parts.append(1.0 if "under_lines" in species.uses else 0.0)
    return sum(parts) / len(parts) if parts else 0.5  # структура неизвестна - нейтрально


def _decor(species: Species) -> float:
    seasonal = len(species.decor_months) / _MONTHS
    return min(1.0, seasonal + (_EVERGREEN_BONUS if species.evergreen else 0.0))
