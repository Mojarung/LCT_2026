"""Участок для индекса качества: граница работ, длина улицы и борта.

Полигонов проезжей части и тротуаров в подоснове Мосгеотреста почти нет (у 16 улиц пилота из
19 их ноль, docs/plans/2026-09-22-green-index-research.md, п. 23), бортовой камень есть
везде. Поэтому пылезащита меряется по бортам, а тень - долей участка под кронами.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.sparse import coo_array
from scipy.sparse.csgraph import connected_components, dijkstra

from green.application.constraints import work_boundary
from green.application.surfaces import Material
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.application.params import PlanParams
    from green.application.surfaces import SurfaceMap
    from green.domain.objects import Feature

# Отрезки борта длиннее этого режутся на равные куски, когда нужен признак грунта у борта:
# доля бортов с грунтом считается в метрах. Точная мера покрытия от разрезки не меняется.
CURB_STEP_M = 1.0
# Шире этого граница работ уже не полоса улицы: в ней дворы или площадь, и «на 1 км улицы»
# теряет смысл. Самый широкий профиль магистральной улицы в Москве - порядка 80 м.
WIDE_STREET_M = 80.0
# Полоса у борта, где кустарник закрывает борт (PlanParams.dust_strip_m по умолчанию): в ней
# ищется грунт, чтобы понять, есть ли у борта вообще место для нижнего яруса.
SOIL_STRIP_M = 2.0
_PROBE_STEP_M = 0.5
_PROBE_DIRECTIONS = 16
_AREA_TYPES = frozenset({"Polygon", "MultiPolygon"})
_LINE_TYPES = frozenset({"LineString", "MultiLineString", "LinearRing"})
# Quality/axis measurement only: protect coincident edges against overlay roundoff.
# Never used by planting footprint checks or regulatory distances.
CURB_CLIP_MARGIN_M = 1e-6
# Скелет границы работ: шаг точек контура, м, и их предел на часть (у огромной границы шаг
# растёт).
AXIS_SPACING_M = 2.0
_AXIS_MAX_POINTS = 20_000
_MIN_AXIS_PART_M2 = 1.0


@dataclass(frozen=True, slots=True)
class Site:
    """Что индексу нужно от чертежа, кроме самих посадок."""

    boundary: BaseGeometry | None
    # Unique curb segments clipped to the work boundary; shape (n, 2, 2), metres.
    curb_segments: NDArray[np.float64]
    # Для каждого отрезка борта: есть ли грунт в полосе SOIL_STRIP_M у его середины по карте
    # покрытий. None - карты покрытий нет, и различить борта нечем.
    curb_soil: NDArray[np.bool_] | None = None

    @property
    def area_m2(self) -> float:
        return float(self.boundary.area) if self.boundary is not None else 0.0

    @property
    def street_length_m(self) -> float | None:
        return street_length(self.boundary) if self.boundary is not None else None


def site_of(features: Sequence[Feature], surface: SurfaceMap | None = None) -> Site:
    boundary = work_boundary(features)
    segments = curb_segments(features, boundary)
    if surface is None:
        return Site(boundary=boundary, curb_segments=segments)
    segments = split_segments(segments, CURB_STEP_M)
    return Site(
        boundary=boundary,
        curb_segments=segments,
        curb_soil=curb_soil(segments.mean(axis=1), surface),
    )


def split_segments(segments: NDArray[np.float64], step_m: float) -> NDArray[np.float64]:
    """Отрезки длиннее step_m - на равные куски не длиннее step_m, в том же порядке."""
    if not len(segments):
        return segments
    start, end = segments[:, 0], segments[:, 1]
    lengths = np.linalg.norm(end - start, axis=1)
    counts = np.maximum(1, np.ceil(lengths / step_m).astype(np.int64))
    owner = np.repeat(np.arange(len(segments)), counts)
    offsets = np.arange(int(counts.sum())) - np.repeat(np.cumsum(counts) - counts, counts)
    total = counts[owner][:, None]
    a = start[owner] + (end - start)[owner] * (offsets[:, None] / total)
    b = start[owner] + (end - start)[owner] * ((offsets[:, None] + 1) / total)
    return np.stack([a, b], axis=1)


def curb_soil(points: NDArray[np.float64], surface: SurfaceMap) -> NDArray[np.bool_]:
    """Есть ли грунт в полосе до SOIL_STRIP_M от точки борта (с любой стороны).

    Проба - кольца 0,5-2,0 м через 0,5 м по 16 направлениям: этого хватает, чтобы газон шириной
    в метр у борта не проскочил между пробами при ячейке карты 0,5 м.
    """
    if not len(points):
        return np.zeros(0, dtype=bool)
    angles = np.linspace(0, 2 * np.pi, _PROBE_DIRECTIONS, endpoint=False)
    radii = np.arange(_PROBE_STEP_M, SOIL_STRIP_M + 1e-9, _PROBE_STEP_M)
    dx = (radii[:, None] * np.cos(angles)[None, :]).ravel()
    dy = (radii[:, None] * np.sin(angles)[None, :]).ravel()
    xs = (points[:, 0:1] + dx[None, :]).ravel()
    ys = (points[:, 1:2] + dy[None, :]).ravel()
    material = surface.material(shapely.points(np.column_stack([xs, ys])))
    return (material == Material.SOIL).reshape(len(points), -1).any(axis=1)


def street_length(boundary: BaseGeometry) -> float:
    """Длина улицы по оси границы работ: самый длинный путь по скелету каждой части, сумма.

    Скелет - рёбра диаграммы Вороного точек контура (через AXIS_SPACING_M), лежащие внутри
    полигона: приближение срединной оси. У полосы L x W самый длинный путь по нему - ось
    длиной L и два уса в углы, всего около L + 0,4 W. Карманы и въезды дают боковые ветви, в
    самый длинный путь они не входят, поэтому длина не растёт от изрезанной границы, как у
    прежней оценки по периметру (в 1,2-5 раз больше длины из записок проекта, у оси - в 0,7-4,4,
    медиана 1,8, docs/notes/34). Двор или площадь в границе ось всё равно удлиняют: для точной
    длины есть параметр street_length_m.
    """
    return _axis_length(shapely.to_wkb(boundary))


def site_length(boundary: BaseGeometry | None, params: PlanParams) -> float | None:
    """Длина улицы для норм «на 1 км»: из записки проекта (параметр), иначе по оси границы."""
    if params.street_length_m:
        return float(params.street_length_m)
    return street_length(boundary) if boundary is not None else None


@lru_cache(maxsize=16)
def _axis_length(wkb: bytes) -> float:
    total = 0.0
    for part in shapely.get_parts(shapely.from_wkb(wkb)):
        if part.geom_type == "Polygon" and part.area > _MIN_AXIS_PART_M2:
            total += _skeleton_diameter(part)
    return total


def _skeleton_diameter(polygon: BaseGeometry) -> float:
    rings = [polygon.exterior, *polygon.interiors]
    spacing = max(AXIS_SPACING_M, sum(r.length for r in rings) / _AXIS_MAX_POINTS)
    coords = np.vstack([shapely.get_coordinates(shapely.segmentize(r, spacing)) for r in rings])
    coords = np.unique(np.round(coords, 3), axis=0)
    if len(coords) < 3:  # noqa: PLR2004 - диаграмме Вороного нужен хотя бы треугольник
        return 0.0
    diagram = shapely.voronoi_polygons(shapely.multipoints(coords), only_edges=True)
    edges = shapely.get_parts(diagram)
    shapely.prepare(polygon)
    inside = edges[shapely.contains(polygon, edges) & (shapely.get_num_coordinates(edges) == 2)]  # noqa: PLR2004
    if not len(inside):
        return 0.0
    ends = shapely.get_coordinates(inside).reshape(-1, 2, 2)
    nodes, inverse = np.unique(np.round(ends.reshape(-1, 2), 3), axis=0, return_inverse=True)
    a, b = inverse.reshape(-1)[0::2], inverse.reshape(-1)[1::2]
    weight = np.linalg.norm(ends[:, 1] - ends[:, 0], axis=1)
    size = len(nodes)
    graph = coo_array(
        (np.r_[weight, weight], (np.r_[a, b], np.r_[b, a])), shape=(size, size)
    ).tocsr()
    count, labels = connected_components(graph, directed=False)
    best = 0.0
    for component in range(count):
        members = np.flatnonzero(labels == component)
        if len(members) < 2:  # noqa: PLR2004 - путь - это хотя бы ребро
            continue
        # Двойной обход: самая дальняя вершина от любой, затем самая дальняя от неё - концы
        # самого длинного пути в дереве; у скелета с кольцами (дыры) это оценка снизу.
        first = dijkstra(graph, indices=members[0])[members]
        far = members[int(np.argmax(np.where(np.isfinite(first), first, -1.0)))]
        second = dijkstra(graph, indices=far)[members]
        best = max(best, float(np.max(np.where(np.isfinite(second), second, 0.0))))
    return best


def curb_segments(
    features: Sequence[Feature], boundary: BaseGeometry | None
) -> NDArray[np.float64]:
    lines: list[BaseGeometry] = []
    for feature in features:
        if feature.object_class is not ObjectClass.CURB:
            continue
        geometry = feature.geometry
        if geometry.geom_type in _AREA_TYPES:
            geometry = geometry.boundary
        if geometry.geom_type in _LINE_TYPES:
            lines.extend(shapely.get_parts(geometry))
    if not lines:
        return np.zeros((0, 2, 2), dtype=np.float64)
    geometry = shapely.union_all(lines)
    if boundary is not None:
        geometry = shapely.intersection(geometry, boundary.buffer(CURB_CLIP_MARGIN_M))
    segments = []
    pending = list(shapely.get_parts(geometry))
    while pending:
        part = pending.pop()
        if part.geom_type in {"MultiLineString", "GeometryCollection"}:
            pending.extend(shapely.get_parts(part))
            continue
        if part.geom_type not in {"LineString", "LinearRing"}:
            continue
        xy = shapely.get_coordinates(part)
        segments.extend(pairwise(xy))
    result = np.asarray(segments, dtype=np.float64).reshape(-1, 2, 2)
    return result[np.any(result[:, 0] != result[:, 1], axis=1)]
