"""Существующие насаждения чертежа: сколько деревьев и кустов уже растёт и где их кроны.

Индексу и балансу «было - стало» нужны стволы, а не метки. Дерево подосновы бывает вставкой
знака (одна точка на дерево) или разобранным знаком: дуги, штриховки и отрезки, у Багрицкого
22 851 метка на 1228 деревьев дендрологического обоснования. Метки без знака склеиваются в
стволы одиночной связью: ближе MERGE_M друг к другу - одно дерево (Багрицкого: 1140 стволов в
границе работ против 1228 по обоснованию, 27.09.2026). Метки у ствола-знака входят в него.
«Полоса деревьев» (ряд кружков, tree_strips) - условный знак полосы, а не стволы: её точки
идут отдельно и в счёт деревьев не входят.

Крону чертёж не даёт (знак дерева - кружок 3 мм, а не крона), поэтому у всех стволов один
диаметр crown_m (параметр existing_crown_m). Счёт по чертежу - оценка: точное число даёт
перечётная ведомость.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import KDTree

from green.application.shrub_strips import SHRUB_STRIP_SOURCE
from green.application.tree_strips import STRIP_SOURCE
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature

MERGE_M = 1.0  # метки ближе друг к другу - один ствол
# Диаметр кроны существующего дерева по умолчанию: медиана взрослой кроны деревьев каталога,
# та же, что у цели тени индекса (canopy_crown_m).
EXISTING_CROWN_M = 8.5
# Метки одного дерева в разобранном знаке лежат дальше MERGE_M друг от друга: для ярусности и
# подлеска стволы ещё раз склеиваются в масштабе кроны, иначе один куст стоит «под» несколькими
# псевдостволами (Багрицкого: у 49% стволов по меткам сосед ближе 3 м). Посадка деревьев с
# шагом ближе 3 м в практике не встречается (743-ПП, табл. 3.6.2: шаг 5-6 м).
CROWN_MERGE_M = 3.0
CIRCLE_SEGMENTS = 8  # четверть окружности кроны - 8 отрезков, как у крон индекса
_EMPTY_XY = np.zeros((0, 2), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class Stock:
    """Стволы, кроны и кусты у границы работ; inside - сам ствол внутри границы."""

    trees_xy: NDArray[np.float64]
    trees_radius: NDArray[np.float64]
    inside: NDArray[np.bool_]
    marks: int  # меток деревьев в исходнике, из которых собраны стволы (без полос)
    source: str  # symbols | marks | mixed | none
    strips_xy: NDArray[np.float64]
    shrubs_xy: NDArray[np.float64]
    shrubs_inside: NDArray[np.bool_]
    crown_radius: float = 0.0
    # Деревья для ярусности и подлеска: стволы, склеенные при CROWN_MERGE_M.
    crown_xy: NDArray[np.float64] = field(default_factory=lambda: _EMPTY_XY)
    crown_inside: NDArray[np.bool_] = field(default_factory=lambda: np.zeros(0, dtype=bool))
    # Объединение существующих крон стволов в границе работ: считается один раз на
    # прогон, индекс сравнивает с ним сотни пробных планов.
    canopy: BaseGeometry | None = None

    @property
    def trees(self) -> int:
        return int(self.inside.sum())

    @property
    def shrubs(self) -> int:
        return int(self.shrubs_inside.sum())

    def crowns(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Центры и радиусы существующих крон; неопределённые знаки полос крон не задают."""
        xy = self.trees_xy
        return xy, np.full(len(xy), self.crown_radius)


EMPTY_STOCK = Stock(
    trees_xy=_EMPTY_XY,
    trees_radius=np.zeros(0),
    inside=np.zeros(0, dtype=bool),
    marks=0,
    source="none",
    strips_xy=_EMPTY_XY,
    shrubs_xy=_EMPTY_XY,
    shrubs_inside=np.zeros(0, dtype=bool),
)


def stock_of(
    features: Sequence[Feature], boundary: BaseGeometry | None, *, crown_m: float
) -> Stock:
    if boundary is None or boundary.is_empty:
        return EMPTY_STOCK
    radius = max(crown_m, 0.0) / 2
    symbols: dict[str, list[tuple[float, float]]] = {}
    marks: list[tuple[float, float]] = []
    strips: list[tuple[float, float]] = []
    counted = 0
    for f in features:
        if f.object_class is not ObjectClass.EXISTING_TREE:
            continue
        if f.source_entity_type == STRIP_SOURCE:
            strips += (
                [(p.x, p.y) for p in shapely.get_parts(f.geometry)]
                if f.geometry.geom_type in {"Point", "MultiPoint"}
                else [_centre(f)]
            )
            continue
        counted += 1
        if f.symbol:
            symbols.setdefault(f.symbol, []).append(_centre(f))
        elif f.geometry.geom_type == "MultiPoint":
            marks += [(p.x, p.y) for p in shapely.get_parts(f.geometry)]
        else:
            marks.append(_centre(f))
    trunks = [tuple(np.mean(points, axis=0)) for points in symbols.values()]
    clusters = _clusters(np.array(marks, dtype=np.float64).reshape(-1, 2), MERGE_M)
    if trunks and len(clusters):
        near = KDTree(np.array(trunks)).query(clusters, distance_upper_bound=MERGE_M)[0]
        clusters = clusters[~np.isfinite(near)]
    xy = np.vstack([np.array(trunks, dtype=np.float64).reshape(-1, 2), clusters])
    reach = shapely.buffer(boundary, radius) if radius > 0 else boundary
    keep = shapely.contains_xy(reach, xy[:, 0], xy[:, 1]) if len(xy) else np.zeros(0, bool)
    xy = xy[keep]
    shrubs = _shrubs(features)
    if len(shrubs):
        shrubs = shrubs[shapely.contains_xy(reach, shrubs[:, 0], shrubs[:, 1])]
    strips_xy = np.array(strips, dtype=np.float64).reshape(-1, 2)
    if len(strips_xy):
        strips_xy = strips_xy[shapely.contains_xy(reach, strips_xy[:, 0], strips_xy[:, 1])]
    centres = xy
    canopy = (
        shapely.intersection(
            shapely.union_all(
                shapely.buffer(shapely.points(centres), radius, quad_segs=CIRCLE_SEGMENTS)
            ),
            boundary,
        )
        if len(centres) and radius > 0
        else None
    )
    source = {(True, True): "mixed", (True, False): "symbols", (False, True): "marks"}.get(
        (bool(trunks), bool(len(clusters))), "none"
    )
    return Stock(
        trees_xy=xy,
        trees_radius=np.full(len(xy), radius),
        inside=shapely.contains_xy(boundary, xy[:, 0], xy[:, 1]) if len(xy) else np.zeros(0, bool),
        marks=counted,
        source=source,
        strips_xy=strips_xy,
        shrubs_xy=shrubs,
        shrubs_inside=(
            shapely.contains_xy(boundary, shrubs[:, 0], shrubs[:, 1])
            if len(shrubs)
            else np.zeros(0, bool)
        ),
        crown_radius=radius,
        canopy=canopy,
        crown_xy=(crowns := _clusters(xy, CROWN_MERGE_M)),
        crown_inside=(
            shapely.contains_xy(boundary, crowns[:, 0], crowns[:, 1])
            if len(crowns)
            else np.zeros(0, bool)
        ),
    )


def _centre(feature: Feature) -> tuple[float, float]:
    if feature.circle_center_m is not None:
        return feature.circle_center_m
    point = feature.geometry.centroid
    return (float(point.x), float(point.y))


def _clusters(xy: NDArray[np.float64], distance: float) -> NDArray[np.float64]:
    """Одиночная связь при distance: центр каждой компоненты."""
    if not len(xy):
        return _EMPTY_XY
    pairs = KDTree(xy).query_pairs(distance, output_type="ndarray")
    graph = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(xy), len(xy)))
    count, labels = connected_components(graph, directed=False)
    sums = np.zeros((count, 2))
    np.add.at(sums, labels, xy)
    return sums / np.bincount(labels, minlength=count)[:, None]


def _shrubs(features: Sequence[Feature]) -> NDArray[np.float64]:
    points = [
        (p.x, p.y)
        for f in features
        if f.object_class is ObjectClass.EXISTING_SHRUB
        and f.source_entity_type != SHRUB_STRIP_SOURCE
        for p in (
            shapely.get_parts(f.geometry)
            if f.geometry.geom_type == "MultiPoint"
            else [f.geometry.centroid]
        )
    ]
    return np.array(points, dtype=np.float64).reshape(-1, 2)


__all__ = [
    "CIRCLE_SEGMENTS",
    "CROWN_MERGE_M",
    "EMPTY_STOCK",
    "EXISTING_CROWN_M",
    "MERGE_M",
    "Stock",
    "stock_of",
]
