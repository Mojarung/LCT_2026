"""Сдвиг слабых мест: посадка, стоящая впритык к норме, отходит туда, где запас больше.

Слабое место - посадка, без которой индекс качества чуть выше (docs/notes/29-quality-index.md).
Чаще всего это посадка ровно на норме: 1,00 м до борта при норме 1,00 м. Первая же неточность
подосновы или разбивки на месте превращает её в нарушение. Сервис пробует сдвинуть такую
посадку на 0,3-1 м по двенадцати направлениям и оставляет сдвиг, только если:

- новая точка на грунте, в границе работ и не на твёрдом покрытии;
- все нормы посадки выполнены с вердиктом не хуже прежнего, и вид заново проходит подбор с
  новыми расстояниями (правила по роду и кроне, соль у дороги) - основания в объяснении
  пересобираются, а не остаются от старой точки;
- шаг до соседних посадок не становится меньше нормы;
- запас до ближайшей нормы вырос хотя бы на MIN_GAIN_M.

Каждый сдвиг принимается, только если индекс плана от него вырос: запас до нормы растёт, но
дерево, ушедшее от борта, хуже прикрывает его от пыли, а ряд может потерять ровный шаг. Решает
индекс целиком, а не одно слагаемое. Пробуются только посадки с запасом ниже цели: остальным
сдвиг ничего не даст.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.spatial import KDTree

from green.application.assortment.context import site_context
from green.application.assortment.filters import species_verdict
from green.application.assortment.scoring import percent, score_species
from green.application.barriers import BARRIER_NOTE, NEAR_M
from green.application.constraints import VERDICT_ORDER, ConstraintIndex
from green.application.params import step_with_tolerance
from green.application.placement import planting_index
from green.application.quality import WEAK_PERMILLE, assess, evaluate
from green.application.quality.terms import tightest
from green.application.wording import index_change
from green.domain.norms import DistanceRule, PlantingType
from green.domain.planting import CheckOutcome, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.application.constraints import EvaluationBatch
    from green.application.params import PlanParams
    from green.application.quality import Site
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Placement, Plan

STEPS_M = (0.3, 0.6, 1.0)
DIRECTIONS = 12
MIN_GAIN_M = 0.1  # на столько должен вырасти запас до нормы, иначе сдвиг не стоит того
OPTIONS = 3  # точек на посадку, которые проверяются по индексу целиком
# Сколько слабых мест пробовать: каждая проба - пересчёт индекса (0,1-0,3 с на улице пилота).
MAX_TRIES = 150
_EPS = 1e-9
# 743-ПП, табл. 3.6.2: кустарники в группе - 0,3 м. Между кустарниками и от ствола дерева
# держим не меньше полуметра: ближе посадка уже не читается как отдельная.
SHRUB_GAP_M = 0.5
_NO_SPECIES = "no_species"
_COMPOSITION = "composition"


@dataclass(frozen=True, slots=True)
class Refinement:
    plan: Plan
    weak: int
    moved: int
    before: float | None
    after: float | None
    # Карта покрытий, построенная для проверки грунта: пригодится правке плана.
    surface: SurfaceMap | None = None


def refine_weak(  # noqa: PLR0913 - сценарий передаёт всё, что знает о прогоне
    plan: Plan,
    *,
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    rulebook: RuleBook,
    params: PlanParams,
    site: Site,
    surface: SurfaceMap | None = None,
) -> Refinement:
    quality = plan.quality
    if quality is None or quality.index is None:
        # Без индекса не с чем сравнить результат сдвига: план без границы работ или с
        # нарушениями остаётся как есть.
        return Refinement(plan, 0, 0, None, None)
    weak = [
        p for p in plan.placements if quality.values[p.placement_id].delta * 1000 <= -WEAK_PERMILLE
    ]
    # Ряд (аллея, изгородь) двигается только целиком: куст или дерево, сдвинутые поодиночке,
    # ломают линию ряда. Здесь сдвигаются группы и одиночки.
    tight = [
        p
        for p in weak
        if (t := tightest(p)) is not None
        and t[0] < params.margin_target_m
        and (p.assortment is None or p.assortment.structure_kind != "row")
    ]
    if not tight:
        return Refinement(plan, len(weak), 0, quality.index, quality.index)
    tight.sort(key=lambda p: quality.values[p.placement_id].delta)
    base = planting_index(features, labels, (), params, surface=surface)
    mover = _Mover(plan.placements, base, rulebook, params)
    current, index = plan, quality.index
    moved = 0
    for placement in tight[:MAX_TRIES]:
        for option in mover.options(placement):
            trial = mover.plan_with(current, option)
            score = evaluate(trial, site, params).index
            if score is not None and score > index + _EPS:
                mover.commit(option)
                current, index = trial, score
                moved += 1
                break
    if not moved:
        return Refinement(plan, len(weak), 0, quality.index, quality.index, base.surface)
    refined = assess(current, site, params)
    note = (
        f"Сдвиг от сетей: {moved} из {len(tight)} посадок впритык к сетям сдвинуты на 0,3-1 м от "
        f"ближайшей нормы, индекс качества вырос {index_change(quality.index, index)}."
    )
    refined = replace(refined, warnings=(*refined.warnings, note))
    return Refinement(refined, len(weak), moved, quality.index, index, base.surface)


class _Mover:
    """Сдвигает посадки по одной, держа шаг до соседей по их текущему положению."""

    def __init__(
        self,
        placements: Sequence[Placement],
        base: ConstraintIndex,
        rulebook: RuleBook,
        params: PlanParams,
    ) -> None:
        self.placements = list(placements)
        self._base = base
        self._rulebook = rulebook
        self._params = params
        self._position = {p.placement_id: i for i, p in enumerate(self.placements)}
        self._xy = np.array([(p.x, p.y) for p in self.placements], dtype=np.float64)
        self._tree = np.array([p.planting_type is PlantingType.TREE for p in self.placements])
        self._reach = params.spacing_m + 2 * max(STEPS_M) + 0.5
        self._kd = KDTree(self._xy)
        angles = np.linspace(0.0, 2 * math.pi, DIRECTIONS, endpoint=False)
        self._offsets = np.array(
            [(step * math.cos(a), step * math.sin(a)) for step in STEPS_M for a in angles]
        )
        self._shift = np.hypot(self._offsets[:, 0], self._offsets[:, 1])

    def try_move(self, placement: Placement) -> bool:
        """Сдвинуть в лучшую допустимую точку без оглядки на индекс (для проверки мувера)."""
        for option in self.options(placement):
            self.commit(option)
            return True
        return False

    def options(self, placement: Placement) -> list[Placement]:
        """До OPTIONS лучших допустимых точек: запас до цели больше, сдвиг меньше."""
        current = tightest(placement)
        rules = _rules_of(placement, self._rulebook)
        target = self._params.margin_target_m
        # Запас сверх цели баллов не даёт: посадку с запасом в 9 м двигать незачем.
        if current is None or rules is None or current[0] >= target:
            return []
        barrier = (
            NEAR_M if any(c.outcome is CheckOutcome.BARRIER for c in placement.checks) else None
        )
        index = self._base.with_rules(rules, barrier_distance_m=barrier)
        points = shapely.points(np.array([placement.x, placement.y]) + self._offsets)
        batch = index.evaluate(points)
        slack = batch.slack()
        capped = np.minimum(slack, target)
        plantable = index.plantable(points)
        limit = VERDICT_ORDER.index(placement.verdict)
        # Лучший запас (до цели), из равных - ближайшая точка: сдвиг не больше нужного.
        order = np.lexsort((self._shift, -capped))
        i = self._position[placement.placement_id]
        found: list[Placement] = []
        for k in order.tolist():
            if capped[k] < current[0] + MIN_GAIN_M or len(found) >= OPTIONS:
                break
            verdict = batch.verdict(k)
            if not plantable[k] or verdict in {Verdict.FORBIDDEN, Verdict.UNKNOWN}:
                continue
            if VERDICT_ORDER.index(verdict) > limit:
                continue
            x, y = float(points[k].x), float(points[k].y)
            if not self._spaced(i, x, y):
                continue
            moved = self._rebuilt(
                placement, batch, k, point=(x, y), margins=(current[0], float(slack[k]))
            )
            if moved is not None:
                found.append(moved)
        return found

    def commit(self, moved: Placement) -> None:
        i = self._position[moved.placement_id]
        self.placements[i] = moved
        self._xy[i] = (moved.x, moved.y)

    def plan_with(self, plan: Plan, moved: Placement) -> Plan:
        placements = list(plan.placements)
        placements[self._position[moved.placement_id]] = moved
        return replace(plan, placements=tuple(placements))

    def _spaced(self, i: int, x: float, y: float) -> bool:
        """Шаг до соседей не меньше нормы; уже нарушенный шаг сдвиг не имеет права ухудшить."""
        for j in self._kd.query_ball_point(self._xy[i], self._reach):
            if j == i:
                continue
            old = math.dist(self._xy[i], self._xy[j])
            new = math.dist((x, y), self._xy[j])
            both_trees = self._tree[i] and self._tree[j]
            need = (
                step_with_tolerance(self._params.spacing_m, PlantingType.TREE)
                if both_trees
                else SHRUB_GAP_M
            )
            if new < min(need, old) - 1e-9:
                return False
        return True

    def _rebuilt(
        self,
        placement: Placement,
        batch: EvaluationBatch,
        k: int,
        *,
        point: tuple[float, float],
        margins: tuple[float, float],
    ) -> Placement | None:
        """Посадка в новой точке: проверки, вердикт и основания вида - заново."""
        (x, y), (before, after) = point, margins
        notes = tuple(n for n in placement.notes if n != BARRIER_NOTE)
        if batch.needs_barrier(k):
            notes = (*notes, BARRIER_NOTE)
        shift = math.dist((placement.x, placement.y), (x, y))
        moved_note = (
            f"сдвинута сервисом на {_decimal(shift, 1)} м от ближайшей нормы: запас "
            f"вырос с {_decimal(before)} до {_decimal(after)} м"
        )
        notes = (*notes, moved_note)
        moved = replace(
            placement, x=x, y=y, checks=batch.checks(k), verdict=batch.verdict(k), notes=notes
        )
        info = placement.assortment
        if info is None or info.status == _NO_SPECIES:
            return moved
        params = replace(self._params, planting_type=placement.planting_type)
        ctx = site_context(moved, info.structure_id, info.structure_kind)
        verdict = species_verdict(placement.species, ctx, self._rulebook, params)
        if not verdict.allowed:
            return None
        score = score_species(placement.species, ctx, params)
        composition = tuple(r for r in info.reasons if r.kind == _COMPOSITION)
        return replace(
            moved,
            assortment=replace(
                info,
                percent=percent(score),
                factors=score.factors,
                reasons=(*verdict.reasons, *composition),
            ),
        )


def _rules_of(placement: Placement, rulebook: RuleBook) -> tuple[DistanceRule, ...] | None:
    """Те же правила и пороги, по которым посадку проверили на её месте."""
    rules = []
    for check in placement.checks:
        rule = rulebook.rule(check.rule_id)
        if not isinstance(rule, DistanceRule):
            return None
        if check.threshold_m is not None:
            rule = replace(rule, min_distance_m=check.threshold_m)
        rules.append(rule)
    return tuple(rules)


def _decimal(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


__all__ = ["MIN_GAIN_M", "STEPS_M", "Refinement", "refine_weak"]
