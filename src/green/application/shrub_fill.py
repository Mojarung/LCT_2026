"""Группы кустарника на газоне до нижней границы плотности: там, где дереву места нет.

Кустарнику нормы мягче, чем дереву: до силового кабеля 0,7 м против 2,0 м, до края проезжей
части 1,0 м против 2,0 м (743-ПП, табл. 3.6.1). На узких улицах с сетями деревья и изгородь
занимают всё, что могут, а кустарников остаётся десятки на километр при рекомендации МГСН
1.02-02, табл. В.1 - 600-720 на 1 км улицы. Этот этап ставит группы кустарника на оставшийся
газон, пока кустарников на улице меньше нижней границы вилки. Больше - нет: заказчик сказал
«лучший вариант не самый плотный».

Правила этой версии:

- центр группы - ячейка грунта через 1 м в границе работ, не ближе 3 м к стволам (крона и
  ком дерева) и 2 м к уже посаженным кустам; между центрами не меньше 4 м;
- в центре кустарник допустим без условий (вердикт «допускается»), точки группы проверяются
  всеми нормами кустарника, как у групп на пустых местах дерева (квадрат 3 x 3 с шагом 1 м);
- к стволу точка группы не ближе 1,25 м, к другому кусту не ближе 0,5 м;
- виды - тем же подбором с квотами кустарников, что у групп на пустых местах дерева.

Приём найден экспериментами docs/notes/30-pipeline-experiments.md (E49).
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.application.assortment import GIVEN, SINGLE, assign_species
from green.application.constraints import ConstraintIndex, work_boundary
from green.application.params import active_distance_rules
from green.application.placement import MODE_LABELS, MODE_SHRUB_FILL, curb_lines, planting_index
from green.application.quality.site import street_length
from green.application.surfaces import Material
from green.application.wording import counted
from green.application.zones import MAX_ZONE_POINTS
from green.domain.norms import PlantingType
from green.domain.planting import SHRUB_FORMS, Plan, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry import LineString

    from green.application.params import PlanParams
    from green.application.placement import PlacementStrategy
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Placement, Species

FILL_LABEL = MODE_LABELS[MODE_SHRUB_FILL]
_CELL_M = 1.0
_TRUNK_GAP_M = 1.25  # как у ряда под аллеей: ком дерева и траншея (shrub_row_tree_gap_m)
_SHRUB_GAP_M = 0.5
# Запас на округление координат до миллиметра (как у групп кустарника в placement.py).
_PIT_RESERVE_M = 0.002


def fill_shrub_gaps(  # noqa: PLR0913 - сценарий передаёт всё, что знает о прогоне
    plan: Plan,
    *,
    strategy: PlacementStrategy,
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    rulebook: RuleBook,
    catalog: Sequence[Species],
    params: PlanParams,
    surface: SurfaceMap | None = None,
) -> Plan:
    if (
        not params.shrub_fill
        or params.planting_type is not PlantingType.TREE
        or params.assortment_mode in {GIVEN, SINGLE}
    ):
        return plan
    boundary = work_boundary(features)
    shrubs = sorted((s for s in catalog if s.life_form in SHRUB_FORMS), key=lambda s: s.code)
    if boundary is None or not shrubs:
        return plan
    shrubs_now = sum(1 for p in plan.placements if p.planting_type is PlantingType.SHRUB)
    goal = params.density_shrubs_per_km[0] * street_length(boundary) / 1000
    size = params.shrub_group_size**2
    groups = math.ceil((goal - shrubs_now) / size) if goal > shrubs_now else 0
    if not groups:
        return plan
    shrub_params = _group_params(params)
    index = planting_index(
        features,
        labels,
        active_distance_rules(rulebook, shrub_params),
        shrub_params,
        surface=surface,
    )
    centers = _centers(plan, index, params, groups, curb_lines(features))
    if not centers:
        return plan
    points = strategy.shrub_groups(
        features, labels, rulebook, shrubs[0], shrub_params, centers=centers
    )
    drafts = tuple(
        replace(p, placement_id=f"F{p.placement_id}", notes=(FILL_LABEL, *p.notes[1:]))
        for p in _clear(points, plan, shrub_params)
    )
    assigned = assign_species(
        Plan(placements=drafts, rejections=()), rulebook, catalog, shrub_params
    )
    start = len(plan.placements)
    added = [replace(p, number=start + i) for i, p in enumerate(assigned.placements, 1)]
    if not added:
        return plan
    summary = (
        "Группы кустарника на газоне: "
        f"{counted(len(centers), 'группа', 'группы', 'групп')}, "
        f"{counted(len(added), 'куст', 'куста', 'кустов')} - кустарников "
        f"было {shrubs_now}, нижняя граница МГСН 1.02-02, табл. В.1 - {goal:.0f} на эту улицу "
        f"({params.density_shrubs_per_km[0]:g} на 1 км)."
    )
    return replace(
        plan,
        placements=(*plan.placements, *added),
        warnings=(*plan.warnings, summary, *(f"Кустарники: {w}" for w in assigned.warnings)),
    )


def _group_params(params: PlanParams) -> PlanParams:
    """Те же параметры групп и квоты кустарников, что у групп на пустых местах дерева."""
    return replace(
        params,
        planting_type=PlantingType.SHRUB,
        spacing_m=params.shrub_group_spacing_m,
        structure_patch_size=params.shrub_group_size**2,
        quota_species=params.shrub_quota_species,
        quota_genus=params.shrub_quota_genus,
        quota_family=params.shrub_quota_family,
        conifer_share=params.shrub_conifer_share,
    )


def _centers(
    plan: Plan,
    index: ConstraintIndex,
    params: PlanParams,
    groups: int,
    curbs: Sequence[LineString],
) -> list[tuple[float, float]]:
    """Центры групп: грунт, допустимо без условий, в стороне от стволов и кустов.

    Обход - от борта вглубь: ближние к борту места первыми. Так группы идут вдоль улицы и
    прикрывают борт от пыли, а не забивают первый попавшийся газон ковром.
    """
    surface = index.surface
    if surface is None:
        return []
    stride = max(1, round(_CELL_M / surface.cell))
    soil = surface.grid[::stride, ::stride] == Material.SOIL
    while soil.sum() > MAX_ZONE_POINTS:  # огромная граница: шаг растёт, как у зон
        stride *= 2
        soil = surface.grid[::stride, ::stride] == Material.SOIL
    rows, cols = np.nonzero(soil)
    xy = np.column_stack(
        [
            surface.origin[0] + (cols * stride + 0.5) * surface.cell,
            surface.origin[1] + (rows * stride + 0.5) * surface.cell,
        ]
    )
    points = shapely.points(xy)
    keep = index.plantable(points)
    for kind, gap in (
        (PlantingType.TREE, params.shrub_fill_tree_gap_m),
        (PlantingType.SHRUB, params.shrub_fill_shrub_gap_m),
    ):
        _away(keep, points, [p for p in plan.placements if p.planting_type is kind], gap)
    candidates = np.flatnonzero(keep)
    if not len(candidates):
        return []
    batch = index.evaluate(points[candidates])
    order = np.arange(len(candidates))
    if curbs:
        tree = shapely.STRtree(list(curbs))
        _, distance = tree.query_nearest(
            points[candidates], return_distance=True, all_matches=False
        )
        order = np.argsort(distance, kind="stable")
    step = params.shrub_fill_step_m
    cells: dict[tuple[int, int], list[tuple[float, float]]] = {}
    centers: list[tuple[float, float]] = []
    for row in order.tolist():
        k = int(candidates[row])
        if batch.verdict(row) is not Verdict.ALLOWED:
            continue
        x, y = float(xy[k, 0]), float(xy[k, 1])
        cx, cy = math.floor(x / step), math.floor(y / step)
        if any(
            math.hypot(px - x, py - y) < step
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for px, py in cells.get((cx + dx, cy + dy), ())
        ):
            continue
        cells.setdefault((cx, cy), []).append((x, y))
        centers.append((x, y))
        if len(centers) >= groups:
            break
    return centers


def _away(
    keep: NDArray[np.bool_],
    points: NDArray[np.object_],
    placements: Sequence[Placement],
    gap: float,
) -> None:
    if not placements or not keep.any():
        return
    tree = shapely.STRtree(shapely.points([(p.x, p.y) for p in placements]))
    hits = tree.query(points, predicate="dwithin", distance=gap)
    keep[np.unique(hits[0])] = False


def _clear(points: Sequence[Placement], plan: Plan, params: PlanParams) -> list[Placement]:
    """Точки групп не ближе к стволам и уже посаженным кустам, чем позволяют ямы: сумма
    радиусов посадочных мест, как у проверки плана (validation)."""
    trees = [(p.x, p.y) for p in plan.placements if p.planting_type is PlantingType.TREE]
    shrubs = [(p.x, p.y) for p in plan.placements if p.planting_type is PlantingType.SHRUB]
    shrub_pit = params.shrub_planting_radius_m
    trunk_gap = max(_TRUNK_GAP_M, params.planting_radius_m + shrub_pit + _PIT_RESERVE_M)
    shrub_gap = max(_SHRUB_GAP_M, 2 * shrub_pit + _PIT_RESERVE_M)
    checks = [
        (shapely.STRtree(shapely.points(coords)), gap)
        for coords, gap in ((trees, trunk_gap), (shrubs, shrub_gap))
        if coords
    ]
    clear = []
    for placement in points:
        point = shapely.Point(placement.x, placement.y)
        if any(len(tree.query(point, predicate="dwithin", distance=gap)) for tree, gap in checks):
            continue
        clear.append(placement)
    return clear


__all__ = ["FILL_LABEL", "fill_shrub_gaps"]
