"""Кустарник под кроной дерева: второй ярус там, где ряд у борта не встал.

МГСН 1.02-02, п. 4.2.9.2 велит ставить под кронами ряды кустарника, заказчик называет
многоярусность признаком хорошей улицы (docs/notes/15-organizers-qa.md, вопрос 15). Ряд у борта
(shrub_rows) встаёт не везде: борт у тротуара, люки, разрывы газона. Тогда под кроной дерева
ставится малая группа (743-ПП, п. 10.8.1: малые группы - 2-3 растения).

Правила этой версии:

- точки - на кольцах 1,5-2,5 м от ствола по двенадцати направлениям, но внутри взрослой кроны:
  ближе 1,25 м к стволу нельзя (ком дерева и траншея, как у ряда - shrub_row_tree_gap_m);
- каждая точка проходит все нормы кустарника, стоит на грунте, в границе работ, не ближе
  1,0 м к люку и 0,8 м к другим кустам;
- вид один на группу, теневыносливый или полутеневой (под кроной тень), без колючек и яда,
  не массовый аллерген, без «-» для категории территории; соседние группы - разные виды;
- дерево, под кроной которого кустарник уже есть (ряд, группа), не трогается.

Исследование, давшее этот приём, - docs/notes/30-pipeline-experiments.md (E11, E19).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.spatial import KDTree

from green.application.assortment.context import site_context
from green.application.assortment.scoring import percent, score_species
from green.application.constraints import work_boundary
from green.application.params import active_distance_rules
from green.application.placement import MODE_ALLEY, MODE_LABELS, MODE_UNDERSTORY, planting_index
from green.application.quality.site import site_length
from green.application.shrub_rows import Blockers, ranked_species
from green.application.stock import EMPTY_STOCK, Stock, stock_of
from green.application.wording import counted, decimal
from green.domain.norms import PlantingType
from green.domain.planting import SHRUB_FORMS, AssortmentInfo, Placement, Reason, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from green.application.constraints import ConstraintIndex, EvaluationBatch
    from green.application.params import PlanParams
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Plan, Species

UNDER_LABEL = MODE_LABELS[MODE_UNDERSTORY]
ALLEY_LABEL = MODE_LABELS[MODE_ALLEY]
_DIRECTIONS = 12
_SHRUB_GAP_M = 0.8  # между кустами группы: крона кустарника через 10 лет 0,8-2,5 м
# Запас на округление координат до миллиметра: две округлённые точки сходятся не больше
# чем на sqrt(2) мм (тот же запас, что у групп кустарника в placement.py).
_PIT_RESERVE_M = 0.002
_ROTATE = 3  # соседние группы берут виды по кругу из трёх лучших
_BASIS = "МГСН 1.02-02, п. 4.2.9.2; 743-ПП, п. 10.8.1"
_GIVEN = "given"
_SINGLE = "single"


def fill_understory(  # noqa: PLR0913 - сценарий передаёт всё, что знает о прогоне
    plan: Plan,
    *,
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    rulebook: RuleBook,
    catalog: Sequence[Species],
    params: PlanParams,
    surface: SurfaceMap | None = None,
) -> Plan:
    if (
        not params.understory
        or params.planting_type is not PlantingType.TREE
        or params.assortment_mode in {_GIVEN, _SINGLE}
    ):
        return plan
    # Деревья аллеи первыми (МГСН 1.02-02, п. 4.2.9.2 - ряды кустарника под кронами на улице),
    # затем остальные: при потолке кустарника на улицу ярус получает сначала аллея.
    trees = sorted(
        (
            p
            for p in plan.placements
            if p.planting_type is PlantingType.TREE
            and (params.understory_trees == "all" or ALLEY_LABEL in p.notes)
        ),
        key=lambda p: ALLEY_LABEL not in p.notes,
    )
    budget = _shrub_budget(plan, features, params)
    species = understory_species(catalog, params.planting_category)
    stock = (
        stock_of(features, work_boundary(features), crown_m=params.existing_crown_m)
        if params.understory_existing
        else EMPTY_STOCK
    )
    if not (trees or stock.trees) or not species:
        return plan
    shrub_params = replace(params, planting_type=PlantingType.SHRUB)
    index = planting_index(
        features,
        labels,
        active_distance_rules(rulebook, shrub_params),
        shrub_params,
        surface=surface,
    )
    planter = _Planter(
        plan, features, index=index, species=species, rulebook=rulebook, params=shrub_params
    )
    # Порядок при потолке кустарника: аллея (ряды под кронами на улице), затем существующие
    # деревья (их взрослые кроны уже дают тень нижнему ярусу), затем остальные новые.
    alley = [t for t in trees if ALLEY_LABEL in t.notes]
    for tree in alley:
        if budget is not None and len(planter.added) >= budget:
            break
        planter.under(tree)
    planter.under_existing(stock, budget)
    for tree in trees[len(alley) :]:
        if budget is not None and len(planter.added) >= budget:
            break
        planter.under(tree)
    if not planter.added:
        return plan
    start = len(plan.placements)
    added = [replace(p, number=start + i) for i, p in enumerate(planter.added, 1)]
    summary = (
        "Кустарник под кронами: "
        f"{counted(planter.groups, 'группа', 'группы', 'групп')}, "
        f"{counted(len(added), 'куст', 'куста', 'кустов')} под деревьями без "
        "нижнего яруса (МГСН 1.02-02, п. 4.2.9.2)"
    )
    if planter.existing_groups:
        summary += (
            f", из них {counted(planter.existing_groups, 'группа', 'группы', 'групп')} под "
            f"существующими деревьями не ближе {decimal(params.understory_existing_gap_m)} м "
            "к стволу (743-ПП, п. 9.8, по аналогии)"
        )
    summary += "."
    return replace(plan, placements=(*plan.placements, *added), warnings=(*plan.warnings, summary))


def _shrub_budget(plan: Plan, features: Sequence[Feature], params: PlanParams) -> int | None:
    """Сколько кустов ещё можно до верхней границы МГСН 1.02-02, табл. В.1 (720 на 1 км) на
    улицу вместе с уже посаженными; None - длина улицы неизвестна, потолка нет."""
    length = site_length(work_boundary(features), params)
    if not length:
        return None
    shrubs = sum(1 for p in plan.placements if p.planting_type is PlantingType.SHRUB)
    return max(0, math.floor(params.density_shrubs_per_km[1] * length / 1000) - shrubs)


def understory_species(catalog: Sequence[Species], category: str) -> list[Species]:
    """Под кроной: теневыносливый или полутеневой, без колючек и яда, не массовый аллерген."""
    return sorted(
        (
            s
            for s in catalog
            if s.life_form in SHRUB_FORMS
            and s.light in {"shade", "semi"}
            and not s.thorny
            and not s.toxic
            and s.allergen < 2  # noqa: PLR2004 - массовый аллерген запрещён 743-ПП п. 3.6.18
            and s.categories.get(category) != "minus"
        ),
        key=lambda s: s.code,
    )


class _Taken:
    """Кусты, уже поставленные этим этапом: проверка «ближе gap» по ячейкам сетки."""

    def __init__(self, gap: float) -> None:
        self._gap = gap
        self._cells: dict[tuple[int, int], list[tuple[float, float]]] = {}

    def near(self, x: float, y: float) -> bool:
        cx, cy = math.floor(x / self._gap), math.floor(y / self._gap)
        return any(
            math.hypot(px - x, py - y) < self._gap
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for px, py in self._cells.get((cx + dx, cy + dy), ())
        )

    def add(self, x: float, y: float) -> None:
        key = (math.floor(x / self._gap), math.floor(y / self._gap))
        self._cells.setdefault(key, []).append((x, y))


class _Planter:
    """Ставит группы под кронами по одной и помнит, что уже поставлено."""

    def __init__(  # noqa: PLR0913 - всё, что нужно для проверки точки и выбора вида
        self,
        plan: Plan,
        features: Sequence[Feature],
        *,
        index: ConstraintIndex,
        species: Sequence[Species],
        rulebook: RuleBook,
        params: PlanParams,
    ) -> None:
        self._index = index
        self._species = species
        self._rulebook = rulebook
        self._params = params
        self._blockers = Blockers(plan, features, params)
        shrubs = [(p.x, p.y) for p in plan.placements if p.planting_type is PlantingType.SHRUB]
        self._covered = shapely.STRtree(shapely.points(shrubs)) if shrubs else None
        self._accepted = {Verdict.ALLOWED}
        if params.allow_needs_approval:
            self._accepted.add(Verdict.NEEDS_APPROVAL)
        angles = np.linspace(0.0, 2 * math.pi, _DIRECTIONS, endpoint=False)
        self._ring = np.column_stack([np.cos(angles), np.sin(angles)])
        self._taken = _Taken(_SHRUB_GAP_M)
        self.added: list[Placement] = []
        self.groups = 0
        self.existing_groups = 0

    def under(self, tree: Placement) -> None:
        radius = max(tree.species.crown_mature_m or tree.species.crown_diameter_m, 0.0) / 2
        # Ямы не перекрываются: куст не ближе к стволу, чем сумма радиусов посадочных мест
        # дерева и кустарника - та же сумма, что у проверки плана (validation).
        params = self._params
        pits = params.planting_radius_m + params.shrub_planting_radius_m + _PIT_RESERVE_M
        rings = [r for r in params.understory_radii_m if pits <= r < radius]
        self._under_at(
            (tree.x, tree.y),
            radius,
            rings,
            key=tree.placement_id,
            why="второй ярус под кроной: малая группа из {n}, 1,5-2,5 м от ствола",
        )

    def under_existing(self, stock: Stock, budget: int | None) -> None:
        """Группы под кронами существующих деревьев в границе, у которых кустарника нет."""
        gap = self._params.understory_existing_gap_m
        radius = stock.crown_radius
        start = gap + _PIT_RESERVE_M  # округление до мм не подводит куст ближе gap
        rings = [r for r in (start, start + 0.5, start + 1.0) if r < radius]
        own = KDTree(stock.shrubs_xy) if len(stock.shrubs_xy) else None
        # Не ближе gap к любому стволу, а не только к своему: соседняя метка может быть
        # настоящим стволом того же или соседнего дерева.
        trunks = KDTree(stock.trees_xy) if len(stock.trees_xy) else None
        why = (
            "второй ярус под кроной существующего дерева: малая группа из {n}, не ближе "
            f"{decimal(gap)} м от ствола (743-ПП, п. 9.8, по аналогии)"
        )
        for n, (x, y) in enumerate(stock.crown_xy[stock.crown_inside].tolist(), 1):
            if budget is not None and len(self.added) >= budget:
                break
            if own is not None and own.query_ball_point((x, y), radius):
                continue
            if self._under_at(
                (x, y), radius, rings, key=f"existing-{n}", why=why, away=(trunks, start)
            ):
                self.existing_groups += 1

    def _under_at(  # noqa: PLR0913 - ствол, крона, кольца, имя группы, основание, запрет
        self,
        trunk_xy: tuple[float, float],
        radius: float,
        rings: Sequence[float],
        *,
        key: str,
        why: str,
        away: tuple[KDTree | None, float] | None = None,
    ) -> bool:
        trunk = shapely.Point(trunk_xy)
        if self._covered is not None and len(
            self._covered.query(trunk, predicate="dwithin", distance=radius)
        ):
            return False
        # Кусты, поставленные этим этапом раньше: под этой кроной ярус уже есть.
        if self.added and np.min(np.hypot(*(self._added_xy() - np.array(trunk_xy)).T)) < radius:
            return False
        if not rings:
            return False
        xy = np.vstack([np.array(trunk_xy) + r * self._ring for r in rings])
        points = shapely.points(xy)
        clear = self._index.plantable(points) & self._blockers.clear(points)
        if away is not None and away[0] is not None:
            clear &= away[0].query(xy)[0] >= away[1]
        if not clear.any():
            return False
        batch = self._index.evaluate(points)
        chosen = self._spread(xy, clear, batch)
        group = self._group(key, why, xy, chosen, batch) if chosen else []
        if not group:
            return False
        self.groups += 1
        self.added.extend(group)
        for shrub in group:
            self._taken.add(shrub.x, shrub.y)
        return True

    def _added_xy(self) -> NDArray[np.float64]:
        return np.array([(p.x, p.y) for p in self.added], dtype=np.float64)

    def _spread(
        self, xy: NDArray[np.float64], clear: NDArray[np.bool_], batch: EvaluationBatch
    ) -> list[int]:
        """До understory_size точек, не ближе _SHRUB_GAP_M друг к другу и к другим группам."""
        chosen: list[int] = []
        for k in np.flatnonzero(clear).tolist():
            if batch.verdict(k) not in self._accepted:
                continue
            x, y = float(xy[k, 0]), float(xy[k, 1])
            if self._taken.near(x, y) or any(
                math.hypot(x - xy[c, 0], y - xy[c, 1]) < _SHRUB_GAP_M for c in chosen
            ):
                continue
            chosen.append(k)
            if len(chosen) == self._params.understory_size:
                break
        return chosen

    def _group(
        self,
        key: str,
        why: str,
        xy: NDArray[np.float64],
        chosen: Sequence[int],
        batch: EvaluationBatch,
    ) -> list[Placement]:
        structure = f"under-{key}"
        drafts = [
            Placement(
                placement_id=f"U{key}-{i}",
                number=0,
                planting_type=PlantingType.SHRUB,
                species=self._species[0],
                x=round(float(xy[k, 0]), 3),
                y=round(float(xy[k, 1]), 3),
                verdict=batch.verdict(k),
                checks=batch.checks(k),
                notes=(UNDER_LABEL,),
            )
            for i, k in enumerate(chosen)
        ]
        contexts = [site_context(d, structure, "group") for d in drafts]
        ranked = ranked_species(self._species, contexts, self._rulebook, self._params)
        if not ranked:
            return []
        kind, verdicts, _ = ranked[self.groups % min(len(ranked), _ROTATE)]
        reason = Reason("reference", why.format(n=len(drafts)), source=_BASIS)
        planted = []
        for draft, verdict, ctx in zip(drafts, verdicts, contexts, strict=True):
            detail = score_species(kind, ctx, self._params)
            planted.append(
                replace(
                    draft,
                    species=kind,
                    assortment=AssortmentInfo(
                        status="assigned",
                        percent=percent(detail),
                        factors=detail.factors,
                        structure_id=structure,
                        structure_kind="group",
                        reasons=(*verdict.reasons, reason),
                    ),
                )
            )
        return planted


__all__ = ["UNDER_LABEL", "fill_understory", "understory_species"]
