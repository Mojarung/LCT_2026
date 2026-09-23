"""Участок для индекса качества: граница работ, длина улицы и борта.

Полигонов проезжей части и тротуаров в подоснове Мосгеотреста почти нет (у 16 улиц пилота из
19 их ноль, docs/plans/2026-09-22-green-index-research.md, п. 23), бортовой камень есть
везде. Поэтому пылезащита меряется по бортам, а тень - долей участка под кронами.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.application.constraints import work_boundary
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature

_AREA_TYPES = frozenset({"Polygon", "MultiPolygon"})
_LINE_TYPES = frozenset({"LineString", "MultiLineString", "LinearRing"})


@dataclass(frozen=True, slots=True)
class Site:
    """Что индексу нужно от чертежа, кроме самих посадок."""

    boundary: BaseGeometry | None
    # Unique curb segments clipped to the work boundary; shape (n, 2, 2), metres.
    curb_segments: NDArray[np.float64]

    @property
    def area_m2(self) -> float:
        return float(self.boundary.area) if self.boundary is not None else 0.0

    @property
    def street_length_m(self) -> float | None:
        return street_length(self.boundary) if self.boundary is not None else None


def site_of(features: Sequence[Feature]) -> Site:
    boundary = work_boundary(features)
    return Site(boundary=boundary, curb_segments=curb_segments(features, boundary))


def street_length(boundary: BaseGeometry) -> float:
    """Длина улицы по границе работ: длина прямоугольника той же площади и периметра.

    Для полосы L x W периметр 2(L + W) и площадь LW дают L = (P + sqrt(P² - 16A)) / 4. Граница
    улицы - вытянутая полоса, так что это её длина по оси; изломы границы (карманы, въезды)
    удлиняют периметр и завышают длину, то есть занижают плотность, а не выдумывают её.
    """
    total = 0.0
    for part in shapely.get_parts(boundary):
        if part.geom_type != "Polygon" or part.area <= 0:
            continue
        perimeter = float(part.exterior.length)
        area = float(part.area)
        total += (perimeter + math.sqrt(max(perimeter * perimeter - 16 * area, 0.0))) / 4
    return total


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
        geometry = shapely.intersection(geometry, boundary)
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
