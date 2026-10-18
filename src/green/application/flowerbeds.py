"""Цветники из многолетников на газоне плана (п. 3 ТЗ: травянистые покрытия, элементы скверов).

Проектировщики пилота ставят цветники почти на каждой улице (docs/notes/34): у Куликовской два
цветника на 699 и 217 м², у 2-й Прядильной 798 м², у Багрицкого пять смесей. Цветник - часть
газона плана у тротуара или другого покрытия, по которому ходят: место не уже
flowerbed_min_width_m, центр не дальше flowerbed_walk_m от края газона у покрытия. Цветники
идут вдоль улицы не чаще flowerbed_spacing_m, площадь каждого около flowerbed_area_m2, а газон
под ним вырезается. Смесь и плотность посадки - из цветников принятого проекта Куликовской
(config/rules.yaml, flowerbed_mixes): если кроны деревьев плана, существующих деревьев и
массивов закрывают не меньше flowerbed_shade_share цветника, смесь теневая, иначе солнечная.
Нормы отступов СП 42.13330 для цветников не установлены (табл. 9.1 - деревья и кустарники),
основание участка - правило проекта R-LAWN-FLOWER-001 со статусом «не сверено».
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.ndimage import distance_transform_edt
from shapely import STRtree
from shapely.geometry import Point

from green.application.surfaces import Material
from green.domain.norms import LawnKind
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.application.params import PlanParams
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import FlowerbedMix
    from green.domain.objects import Feature
    from green.domain.planting import Placement

# Кандидаты в центры цветника - узлы сетки с этим шагом внутри газона.
GRID_STEP_M = 2.5
# Круг цветника растёт этим множителем, пока не наберёт площадь, но не больше GROWTH_LIMIT
# раз: на узкой полосе газона цветник вытягивается вдоль неё.
GROWTH = 1.2
GROWTH_LIMIT = 4.0
# Меньше этой доли заданной площади цветник не ставится: место слишком тесное.
MIN_AREA_SHARE = 0.8
_LAWN_KINDS = (LawnKind.KEPT, LawnKind.NEW)


def place_flowerbeds(  # noqa: PLR0913 - газоны, посадки, подоснова, карта покрытий, смеси, профиль
    lawns: Sequence[tuple[LawnKind, BaseGeometry]],
    *,
    placements: Sequence[Placement],
    features: Sequence[Feature],
    surface: SurfaceMap,
    mixes: Sequence[FlowerbedMix],
    params: PlanParams,
) -> list[tuple[BaseGeometry, FlowerbedMix, float]]:
    """Цветники: (контур, смесь, доля под кронами) в порядке выбора мест."""
    lawn = shapely.union_all([g for kind, g in lawns if kind in _LAWN_KINDS])
    if lawn.is_empty or not mixes:
        return []
    half = params.flowerbed_min_width_m / 2
    inner = lawn.buffer(-half)
    if inner.is_empty:
        return []
    candidates = _grid_points(inner)
    if not len(candidates):
        return []
    walk = _walk_distance(surface, candidates)
    near = walk <= params.flowerbed_walk_m + half
    candidates, walk = candidates[near], walk[near]
    # Ближе к покрытию - лучше; при равенстве - вдоль улицы по порядку, ответ воспроизводим.
    order = np.lexsort((shapely.get_y(candidates), shapely.get_x(candidates), np.round(walk, 1)))
    parts = shapely.get_parts(lawn)
    tree = STRtree(parts)
    reach = math.sqrt(params.flowerbed_area_m2 / math.pi) * GROWTH_LIMIT
    crowns = _crowns(placements, features, params)
    taken: list[BaseGeometry] = []
    beds: list[tuple[BaseGeometry, FlowerbedMix, float]] = []
    for index in order:
        center = candidates[index]
        if any(center.distance(other) < params.flowerbed_spacing_m for other in taken):
            continue
        # Газон рядом с центром, а не весь газон улицы: пересечение с кругом - на месте.
        local = shapely.union_all(parts[tree.query(center.buffer(reach))])
        bed = _bed(local, center, params.flowerbed_area_m2)
        if bed is None:
            continue
        shade = float(bed.intersection(crowns).area / bed.area) if crowns is not None else 0.0
        beds.append((bed, _mix(mixes, shade >= params.flowerbed_shade_share), shade))
        taken.append(bed.centroid)
    return beds


def plants(mix: FlowerbedMix, area_m2: float) -> tuple[tuple[str, str, int], ...]:
    """Штуки многолетников смеси на площади: плотность смеси x доля вида."""
    total = area_m2 * mix.density_per_m2
    return tuple((p.name_ru, p.name_lat, round(total * p.share)) for p in mix.plants)


def _grid_points(area: BaseGeometry) -> NDArray[np.object_]:
    x0, y0, x1, y1 = area.bounds
    xs = np.arange(x0, x1 + GRID_STEP_M, GRID_STEP_M)
    ys = np.arange(y0, y1 + GRID_STEP_M, GRID_STEP_M)
    gx, gy = np.meshgrid(xs, ys)
    points = shapely.points(gx.ravel(), gy.ravel())
    shapely.prepare(area)
    inside = points[shapely.contains(area, points)]
    if len(inside):
        return inside
    # Место уже шага сетки: одна точка внутри.
    return np.array([area.representative_point()], dtype=object)


def _walk_distance(surface: SurfaceMap, points: NDArray[np.object_]) -> NDArray[np.float64]:
    """Расстояние от точки до ближайшей клетки покрытия на карте покрытий, м."""
    paved = surface.grid == Material.PAVED
    if not paved.any():
        return np.full(len(points), np.inf)
    distances = distance_transform_edt(~paved, sampling=surface.cell)
    xy = shapely.get_coordinates(points)
    cols = np.floor((xy[:, 0] - surface.origin[0]) / surface.cell).astype(np.int64)
    rows = np.floor((xy[:, 1] - surface.origin[1]) / surface.cell).astype(np.int64)
    inside = (rows >= 0) & (rows < paved.shape[0]) & (cols >= 0) & (cols < paved.shape[1])
    result = np.full(len(points), np.inf)
    result[inside] = distances[rows[inside], cols[inside]]
    return result


def _bed(lawn: BaseGeometry, center: Point, area_m2: float) -> BaseGeometry | None:
    """Часть газона вокруг центра площадью не меньше area_m2: круг растёт, пока не наберёт."""
    radius = math.sqrt(area_m2 / math.pi)
    limit = radius * GROWTH_LIMIT
    bed = None
    while radius <= limit:
        piece = _part_at(lawn.intersection(center.buffer(radius)), center)
        if piece is not None:
            bed = piece
            if bed.area >= area_m2:
                break
        radius *= GROWTH
    if bed is None or bed.area < MIN_AREA_SHARE * area_m2:
        return None
    return bed


def _part_at(area: BaseGeometry, center: Point) -> BaseGeometry | None:
    parts = [p for p in shapely.get_parts(area) if p.geom_type == "Polygon" and not p.is_empty]
    for part in parts:
        if part.covers(center):
            return part
    return None


def _crowns(
    placements: Sequence[Placement], features: Sequence[Feature], params: PlanParams
) -> BaseGeometry | None:
    """Кроны: взрослые кроны деревьев плана, существующие деревья и массивы чертежа."""
    shapes: list[BaseGeometry] = [
        Point(p.x, p.y).buffer((p.species.crown_mature_m or p.species.crown_diameter_m) / 2)
        for p in placements
        if p.species.is_tree
    ]
    for feature in features:
        if feature.object_class is ObjectClass.EXISTING_TREE:
            shapes.append(feature.geometry.buffer(params.existing_crown_m / 2))
        elif feature.object_class is ObjectClass.EXISTING_WOODLAND and feature.geometry.area:
            shapes.append(feature.geometry)
    return shapely.union_all(shapes) if shapes else None


def _mix(mixes: Sequence[FlowerbedMix], shaded: bool) -> FlowerbedMix:  # noqa: FBT001
    light = "shade" if shaded else "sun"
    return next((m for m in mixes if m.light == light), mixes[0])


__all__ = ["place_flowerbeds", "plants"]
