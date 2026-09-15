"""Зоны допустимости: карта «где можно сажать» по всем правилам сразу (ТЗ, п. 2).

Сетка точек по грунту (карта покрытий) или по границе работ, каждая точка проверяется
теми же правилами, что и кандидаты в посадку. Ячейки с одним вердиктом склеиваются
в полигоны. Зоны идут на слои GREEN_ZONE_* и в zones.geojson.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.application.constraints import VERDICT_ORDER
from green.application.surfaces import Material
from green.domain.planting import Verdict, Zone

if TYPE_CHECKING:
    from numpy.typing import NDArray

    from green.application.constraints import ConstraintIndex

MAX_ZONE_POINTS = 600_000
ZONE_VERDICTS = (Verdict.ALLOWED, Verdict.NEEDS_APPROVAL)


def build_zones(index: ConstraintIndex, cell_m: float) -> tuple[Zone, ...]:
    xy, cell = _grid(index, cell_m)
    if not len(xy):
        return ()
    points = shapely.points(xy)
    keep = index.plantable(points)
    xy, points = xy[keep], points[keep]
    if not len(points):
        return ()
    codes = index.evaluate(points).verdict_codes
    zones = []
    half = cell / 2
    for verdict in ZONE_VERDICTS:
        selected = xy[codes == VERDICT_ORDER.index(verdict)]
        if not len(selected):
            continue
        xs, ys = selected[:, 0], selected[:, 1]
        boxes = shapely.box(xs - half, ys - half, xs + half, ys + half)
        merged = shapely.simplify(shapely.coverage_union_all(boxes), cell * 0.3)
        if not merged.is_empty:
            zones.append(Zone(verdict=verdict, geometry=merged))
    return tuple(zones)


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
