"""Борт тротуара и борт проезжей части.

В топоплане бортовой камень разделяет и проезжую часть с тротуаром, и тротуар с газоном; сторона
у линии не записана. Поэтому любой борт принимался краем проезжей части (2,0 / 1,0 м по СП
42.13330.2016, табл. 9.1). Аудит Берзарина 16.10.2026: из 128 срабатываний по борту 104 - борта
тротуара в метрах от проектной проезжей части, а норма края тротуара - 0,7 / 0,5 м.

Часть борта становится краем тротуара (класс pavement_edge, правило «край тротуара и садовой
дорожки»), только когда это доказано геометрией:

- она дальше KERB_ON_ROAD_M от полигонов проезжей части,
- лежит на тротуаре или ближе KERB_ON_WALK_M к нему,
- и по другую сторону газон не дальше KERB_ON_LAWN_M (борт между тротуаром и газоном).

Борт без тротуара рядом и борт у проезжей части не меняются: в сомнении норма не ослабляется.
Полигоны проезжей части должны быть полными (места посадки, places.ROAD_COVERAGE_MIN): участки
ремонта покрытия не доказывают, что у борта вдали от них нет ненарисованной проезжей части.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import shapely

from green.application.places import MIN_ROAD_M2, ROAD_COVERAGE_MIN, curb_coverage
from green.domain.objects import ClassificationEvidence, ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature

KERB_ON_ROAD_M = 1.0  # ближе к полигону проезжей части - борт проезжей части
KERB_ON_WALK_M = 0.3  # на тротуаре или ближе - борт тротуара
KERB_ON_LAWN_M = 0.5  # и газон по другую сторону не дальше
MIN_PIECE_M = 0.5  # короче - обрезок на стыке, остаётся бортом проезжей части
METHOD = "context:kerb_beside_footway"


def refine_kerbs(features: Sequence[Feature]) -> tuple[tuple[Feature, ...], str | None]:
    """Борта тротуаров - краем тротуара; возвращает объекты и пояснение, если борта не тронуты."""
    roads = [
        f.geometry
        for f in features
        if f.object_class is ObjectClass.ROAD and f.geometry.area >= MIN_ROAD_M2
    ]
    if not roads:
        return tuple(features), (
            "Борта: полигонов проезжей части в чертеже нет - каждый борт проверяется как край "
            "проезжей части (2,0 / 1,0 м)."
        )
    road = shapely.union_all(roads)
    coverage = curb_coverage(road, features)
    if coverage is not None and coverage < ROAD_COVERAGE_MIN:
        return tuple(features), (
            f"Борта: вдоль полигонов проезжей части лишь {coverage:.0%} бортов - полигоны "
            "неполные, каждый борт проверяется как край проезжей части (2,0 / 1,0 м)."
        )
    walks = [
        f.geometry for f in features if f.object_class is ObjectClass.SIDEWALK and f.geometry.area
    ]
    lawns = [f.geometry for f in features if f.object_class is ObjectClass.LAWN and f.geometry.area]
    if not walks or not lawns:
        return tuple(features), None
    near_road = road.buffer(KERB_ON_ROAD_M)
    # Борт тротуара доказан с обеих сторон: тротуар с одной, газон с другой. Тротуар у
    # ненарисованного проезда (полигоны «полные» лишь в среднем) так не пройдёт (ревью 16.10).
    near_walk = (
        shapely.union_all(walks)
        .buffer(KERB_ON_WALK_M)
        .intersection(shapely.union_all(lawns).buffer(KERB_ON_LAWN_M))
    )
    shapely.prepare(near_road)
    shapely.prepare(near_walk)
    out: list[Feature] = []
    for feature in features:
        if feature.object_class is not ObjectClass.CURB:
            out.append(feature)
            continue
        out.extend(_split(feature, near_road, near_walk))
    return tuple(out), None


def _split(feature: Feature, near_road: BaseGeometry, near_walk: BaseGeometry) -> list[Feature]:
    line = feature.geometry
    if not near_walk.intersects(line):
        return [feature]
    beside_walk = line.difference(near_road).intersection(near_walk)
    beside_walk = _lines(beside_walk)
    if beside_walk.length < MIN_PIECE_M:
        return [feature]
    rest = _lines(line.difference(beside_walk.buffer(1e-6)))
    parts = [
        replace(
            feature,
            geometry=beside_walk,
            object_class=ObjectClass.PAVEMENT_EDGE,
            classification=ClassificationEvidence(METHOD),
        )
    ]
    if rest.length > 0:
        parts.append(replace(feature, geometry=rest))  # остаток у проезда - всегда борт
    return parts


def _lines(geometry: BaseGeometry) -> BaseGeometry:
    """Линейные части результата: точки касания и пустые куски не нужны."""
    pieces = [
        part
        for part in shapely.get_parts(geometry)
        if part.geom_type in {"LineString", "MultiLineString"} and part.length > 0
    ]
    return shapely.line_merge(shapely.union_all(pieces)) if pieces else shapely.LineString()


def is_kerb(feature: Feature) -> bool:
    """Бортовой камень для приёмов вдоль борта (аллея, ряд и изгородь, длина бортов индекса):
    и борт проезжей части, и борт тротуара, ставший краем тротуара по норме."""
    if feature.object_class is ObjectClass.CURB:
        return True
    evidence = feature.classification
    return (
        feature.object_class is ObjectClass.PAVEMENT_EDGE
        and evidence is not None
        and evidence.method == METHOD
    )
