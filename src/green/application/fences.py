"""Ограда из штрихов - сплошной линией (Харьковская, 18.10.2026).

Съёмка рисует ограду штрихами: на Харьковской 4 362 куска, 96 % короче 3 м, у четверти
зазор 0,5 м до соседнего. Зазор равен клетке карты покрытий, и материал от подписи («А»)
протекал сквозь ограду на газон, а в 3D-виде ограда стояла с дырами. Здесь зазоры между
штрихами закрываются перемычками - отдельными объектами того же класса и слоя: сами
штрихи не меняются, исходные ссылки на них в объяснениях остаются.

Перемычка ставится, если конец одного штриха смотрит на конец другого: зазор не больше
GAP_M и оба штриха продолжают друг друга с поворотом не круче TURN_DEG. Угол ограды
(поворот круче) закрывается, только если зазор не больше CORNER_GAP_M. Проём шире GAP_M -
калитка или проход - остаётся открытым.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.spatial import KDTree

from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature

GAP_M = 1.0
CORNER_GAP_M = 0.6
TURN_DEG = 30.0
_MIN_POINTS = 2


def bridge_fence_gaps(features: Sequence[Feature]) -> tuple[tuple[Feature, ...], int]:
    """Объекты чертежа и перемычки между штрихами ограды; второе значение - число перемычек."""
    strokes = [
        f
        for f in features
        if f.object_class is ObjectClass.FENCE
        and f.geometry.geom_type == "LineString"
        and len(f.geometry.coords) >= _MIN_POINTS
        and not f.geometry.is_ring
    ]
    if len(strokes) < _MIN_POINTS:
        return tuple(features), 0
    ends, outward = _ends(strokes)
    tree = KDTree(ends)
    limit = math.cos(math.radians(TURN_DEG))
    candidates = []
    for a, b in tree.query_pairs(GAP_M):
        if a // 2 == b // 2:
            continue
        gap = float(np.linalg.norm(ends[a] - ends[b]))
        if gap == 0:
            continue
        straight = _continues(ends[a], outward[a], ends[b], outward[b], limit)
        if straight or gap <= CORNER_GAP_M:
            # Прямое продолжение важнее угла: при равном зазоре берётся первым.
            candidates.append((0 if straight else 1, gap, a, b))
    taken: set[int] = set()
    touching = _touching(tree)
    bridges = []
    for _, _, a, b in sorted(candidates):
        if a in taken or b in taken or a in touching or b in touching:
            continue
        taken.update((a, b))
        source = strokes[a // 2]
        bridges.append(
            replace(
                source,
                geometry=shapely.LineString([ends[a], ends[b]]),
                classification=source.classification,
            )
        )
    return (*features, *bridges), len(bridges)


def _ends(strokes: Sequence[Feature]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Концы штрихов (2k - начало штриха k, 2k + 1 - конец) и направления наружу."""
    ends = []
    outward = []
    for f in strokes:
        coords = np.asarray(f.geometry.coords, dtype=np.float64)[:, :2]
        ends.extend((coords[0], coords[-1]))
        outward.extend((_unit(coords[0] - coords[1]), _unit(coords[-1] - coords[-2])))
    return np.array(ends), np.array(outward)


def _touching(tree: KDTree) -> set[int]:
    """Концы, которые уже стыкуются с другим штрихом: им перемычка не нужна."""
    joined: set[int] = set()
    for a, b in tree.query_pairs(1e-6):
        if a // 2 != b // 2:
            joined.update((a, b))
    return joined


def _unit(v: NDArray[np.float64]) -> NDArray[np.float64]:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _continues(
    pa: NDArray[np.float64],
    da: NDArray[np.float64],
    pb: NDArray[np.float64],
    db: NDArray[np.float64],
    limit: float,
) -> bool:
    toward = _unit(pb - pa)
    return bool(da @ toward >= limit and db @ -toward >= limit and da @ -db >= limit)


# Ось ограды для 3D-вида. Полоса вокруг всех линий ограды шириной 2 x BAND_M: две линии
# условного знака (0,2-0,4 м друг от друга), разрывы штрихов и углы сливаются в одну полосу,
# её срединная линия - ось. Кольца короче POST_RING_M - знаки столбов, не ограда.
BAND_M = 0.35
POST_RING_M = 3.0
# Разрыв между осями короче этого - не проход, ось сшивается, м.
JOIN_M = 1.6
_STEP_M = 0.2
_SPUR_M = 1.2
_AXIS_TOLERANCE_M = 0.12
_GRID_M = 1e-4


def fence_axes(lines: Sequence[BaseGeometry]) -> list[shapely.LineString]:
    """Оси оград: одна линия посередине двойного знака, сшитая через разрывы и углы.

    В съёмке ограда на столбах - две параллельные линии и кружки столбов, часто штрихами; в 3D
    каждая линия вставала своей решёткой, углы не сходились (пользователь, 19.10.2026: «как
    будто человек раскидал объекты»). Ось строится как срединная линия полосы вокруг всех
    линий: рёбра диаграммы Вороного по точкам контура полосы, лежащие внутри неё, без
    коротких отростков к краям."""
    parts = []
    for geometry in lines:
        for part in shapely.get_parts(geometry):
            ring = part.exterior if part.geom_type == "Polygon" else part
            if ring.geom_type not in {"LineString", "LinearRing"} or ring.length == 0:
                continue
            if ring.is_closed and ring.length < POST_RING_M:
                continue
            parts.append(shapely.LineString(ring.coords))
    if not parts:
        return []
    band = shapely.union_all(shapely.buffer(np.array(parts, dtype=object), BAND_M, quad_segs=2))
    axes: list[shapely.LineString] = []
    for polygon in shapely.get_parts(band):
        try:
            axes.extend(_medial_axis(polygon))
        except shapely.errors.GEOSException:
            # Ось этой полосы не построилась - её штрихи идут в 3D как есть, прогон не падает.
            axes.extend(part for part in parts if polygon.contains(part))
    return _join_ends(axes)


def _join_ends(axes: list[shapely.LineString]) -> list[shapely.LineString]:
    """Сшить оси, концы которых ближе JOIN_M: разрывы штрихов шире полосы (у дома 1А на
    Харьковской 0,7-1,5 м) - не проходы. Проход шире JOIN_M остаётся."""
    if len(axes) < _MIN_POINTS:
        return axes
    ends = np.array([c for a in axes for c in (a.coords[0][:2], a.coords[-1][:2])])
    tree = KDTree(ends)
    pairs = sorted(
        (float(np.linalg.norm(ends[i] - ends[j])), i, j)
        for i, j in tree.query_pairs(JOIN_M)
        if i // 2 != j // 2
    )
    used: set[int] = set()
    links = []
    for _, i, j in pairs:
        if i in used or j in used:
            continue
        used.update((i, j))
        links.append(shapely.LineString([ends[i], ends[j]]))
    if not links:
        return axes
    merged = shapely.line_merge(shapely.union_all([*axes, *links]))
    return [g for g in shapely.get_parts(merged) if g.geom_type == "LineString"]


def _medial_axis(polygon: BaseGeometry) -> list[shapely.LineString]:
    # Диаграмма Вороного GEOS падает на повторах точек в больших координатах (Старый Гай,
    # 20 850 м): точки сдвигаются к началу у угла полосы и берутся без повторов.
    offset = np.asarray(polygon.bounds[:2])
    local = shapely.transform(polygon, lambda xy: xy - offset)
    dense = shapely.get_coordinates(shapely.segmentize(local.boundary, _STEP_M))
    points = shapely.multipoints(np.unique(np.round(dense, 6), axis=0))
    edges = shapely.get_parts(shapely.voronoi_polygons(points, only_edges=True))
    edges = shapely.transform(edges, lambda xy: xy + offset)
    shapely.prepare(polygon)
    inside = edges[shapely.contains_properly(polygon, edges)]
    # Рёбра Вороного сходятся с расхождением в 1e-16: без сетки они не склеиваются в линию.
    inside = shapely.set_precision(inside, _GRID_M)
    inside = inside[~shapely.is_empty(inside)]
    if not len(inside):
        return []
    graph = shapely.line_merge(shapely.union_all(inside))
    for _ in range(3):
        graph = _prune(graph)
    return [
        shapely.simplify(line, _AXIS_TOLERANCE_M)
        for line in shapely.get_parts(graph)
        if line.geom_type == "LineString" and line.length > _STEP_M
    ]


def _prune(graph: BaseGeometry) -> BaseGeometry:
    """Срезать отростки: висячие ветви короче _SPUR_M, другой конец которых - развилка."""
    lines = [g for g in shapely.get_parts(graph) if g.geom_type == "LineString"]
    if len(lines) < _MIN_POINTS:
        return graph
    degree: dict[tuple[float, float], int] = {}
    ends = []
    for line in lines:
        a = tuple(np.round(line.coords[0], 6))
        b = tuple(np.round(line.coords[-1], 6))
        ends.append((a, b))
        for key in (a, b):
            degree[key] = degree.get(key, 0) + 1
    kept = [
        line
        for line, (a, b) in zip(lines, ends, strict=True)
        if not (
            line.length < _SPUR_M
            and min(degree[a], degree[b]) == 1
            and max(degree[a], degree[b]) > _MIN_POINTS
        )
    ]
    return shapely.line_merge(shapely.union_all(kept)) if kept else graph


__all__ = ["CORNER_GAP_M", "GAP_M", "JOIN_M", "bridge_fence_gaps", "fence_axes"]
