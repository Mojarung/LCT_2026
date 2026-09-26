"""Зоны допустимости: карта «где можно сажать» по всем правилам сразу (ТЗ, п. 2).

Сетка точек по грунту (карта покрытий) или по границе работ, каждая точка проверяется
теми же правилами, что и кандидаты в посадку. Ячейки с одним вердиктом склеиваются
в полигоны. Зоны идут на слои GREEN_ZONE_* и в zones.geojson.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.application.constraints import VERDICT_ORDER
from green.application.surfaces import Material
from green.domain.planting import Verdict, Zone

if TYPE_CHECKING:
    from collections.abc import Iterable

    from numpy.typing import NDArray

    from green.application.constraints import ConstraintIndex

MAX_ZONE_POINTS = 600_000
ZONE_VERDICTS = (Verdict.ALLOWED, Verdict.NEEDS_APPROVAL)
# Самый плотный шаг деревьев по норме: 743-ПП, табл. 3.6.2 - однорядная 5-6 м, групповая 5-7 м.
DENSEST_STEP_M = 5.0
# Статистика плана: вместимость по местам своего варианта и общая по вариантам портфеля.
CAPACITY_STAT = "capacity_trees"
SITE_CAPACITY_STAT = "site_capacity_trees"


def build_zones(index: ConstraintIndex, cell_m: float) -> tuple[Zone, ...]:
    xy, cell = _grid(index, cell_m)
    if not len(xy):
        return ()
    points = shapely.points(xy)
    # Distance to a closed obstacle is 1-Lipschitz. Every point of the square
    # lies within half its diagonal of the centre, so this margin certifies
    # the entire cell in the configured geometric model.
    margin = cell / np.sqrt(2)
    keep = index.plantable(points, margin_m=margin)
    xy, points = xy[keep], points[keep]
    if not len(points):
        return ()
    codes = index.evaluate(points, margin_m=margin).verdict_codes
    zones = []
    half = cell / 2
    for verdict in ZONE_VERDICTS:
        selected = xy[codes == VERDICT_ORDER.index(verdict)]
        if not len(selected):
            continue
        xs, ys = selected[:, 0], selected[:, 1]
        boxes = shapely.box(xs - half, ys - half, xs + half, ys + half)
        # Simplification could expand the certified squares into forbidden space.
        merged = shapely.union_all(boxes)
        if not merged.is_empty:
            zones.append(Zone(verdict=verdict, geometry=merged))
    return tuple(zones)


def pack_count(points: Iterable[tuple[float, float]], step_m: float = DENSEST_STEP_M) -> int:
    """Сколько деревьев встанет на эти точки с шагом не меньше step_m: жадно, в данном порядке.

    Свойство участка, а не плана, когда точки - все места, прошедшие нормы: узкая полоса вдоль
    борта получает длину / шаг деревьев, широкий газон - почти гексагональную укладку. Нужна
    индексу, чтобы плотность мерилась «при условии допустимости насаждений» (МГСН 1.02-02,
    табл. В.1, сноска).
    """
    cells: dict[tuple[int, int], list[tuple[float, float]]] = {}
    count = 0
    for x, y in points:
        cx, cy = math.floor(x / step_m), math.floor(y / step_m)
        near = any(
            math.hypot(px - x, py - y) < step_m
            for dx in (-1, 0, 1)
            for dy in (-1, 0, 1)
            for px, py in cells.get((cx + dx, cy + dy), ())
        )
        if not near:
            cells.setdefault((cx, cy), []).append((x, y))
            count += 1
    return count


def _grid(index: ConstraintIndex, cell_m: float) -> tuple[NDArray[np.float64], float]:
    """Центры ячеек грунта по карте покрытий, иначе сетка по границе работ."""
    surface = index.surface
    if surface is not None:
        stride = max(1, round(cell_m / surface.cell))
        cell = surface.cell * stride
        soil = surface.grid[::stride, ::stride] == Material.SOIL
        while soil.sum() > MAX_ZONE_POINTS:
            stride *= 2
            cell = surface.cell * stride
            soil = surface.grid[::stride, ::stride] == Material.SOIL
        rows, cols = np.nonzero(soil)
        xs = surface.origin[0] + (cols * stride + 0.5) * surface.cell
        ys = surface.origin[1] + (rows * stride + 0.5) * surface.cell
        return np.column_stack([xs, ys]), cell
    if index.boundary is None:
        return np.zeros((0, 2)), cell_m
    minx, miny, maxx, maxy = index.boundary.bounds
    cell = cell_m
    while ((maxx - minx) / cell) * ((maxy - miny) / cell) > MAX_ZONE_POINTS:
        cell *= 2
    xs = np.arange(minx + cell / 2, maxx, cell)
    ys = np.arange(miny + cell / 2, maxy, cell)
    grid_x, grid_y = np.meshgrid(xs, ys)
    return np.column_stack([grid_x.ravel(), grid_y.ravel()]), cell
