"""Школы и детские сады: здание чертежа, совпавшее с контуром OpenStreetMap.

743-ПП, табл. 3.6.1: от наружной стены школьного здания или здания детского сада дерево - 10 м,
кустарник - 1,5 м (у прочих зданий 5 и 1,5). Назначения здания в топоплане Мосгеотреста нет
(docs/notes/21): школа там такое же «Н», как магазин. Контуры школ и детсадов Москвы - выгрузка
OpenStreetMap (tools/fetch_osm_schools.py), пересчитанная в систему координат чертежа.

Школой становится только здание самого чертежа, которое контур OSM подтверждает: площадь
пересечения с контуром - не меньше половины площади здания или контура, а у здания, нарисованного
линиями стен, - не меньше половины периметра контура лежит у стен (в 2 м). Сдвиг выгрузки,
чужая система координат или контур без нарисованного здания школ не создают. Здание остаётся
зданием (5 м и всё прочее), школа добавляется отдельным объектом с той же геометрией.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import shapely

from green.application.wording import counted, plural
from green.domain.objects import ClassificationEvidence, ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.domain.objects import Feature

MIN_SHARE = 0.5
WALL_GAP_M = 2.0
METHOD = "gis:osm_school"


def mark_schools(
    features: Sequence[Feature], footprints: Sequence[Feature]
) -> tuple[tuple[Feature, ...], str]:
    """Объекты с добавленными школами и строка для журнала прогона ("" - школ нет)."""
    buildings = [f for f in features if f.object_class is ObjectClass.BUILDING]
    outlines = [f.geometry for f in footprints if f.geometry.area > 0]
    if not buildings or not outlines:
        return tuple(features), ""
    tree = shapely.STRtree([b.geometry for b in buildings])
    chosen: dict[int, None] = {}
    matched = 0
    for outline in outlines:
        near = tree.query(outline.buffer(WALL_GAP_M), predicate="intersects")
        found = _confirmed(outline, [buildings[i] for i in near])
        if found:
            matched += 1
            chosen.update(dict.fromkeys(near[i] for i in found))
    if not chosen:
        return tuple(features), ""
    schools = tuple(
        replace(
            buildings[i],
            object_class=ObjectClass.SCHOOL,
            classification=ClassificationEvidence(METHOD),
        )
        for i in sorted(chosen)
    )
    buildings_text = counted(len(schools), "здание", "здания", "зданий")
    outlines_text = counted(matched, "контуром", "контурами", "контурами")
    note = (
        f"Школы и детские сады по OpenStreetMap: {buildings_text} чертежа "
        f"{plural(len(schools), 'совпало', 'совпали', 'совпали')} с "
        f"{outlines_text} OSM; от их стен деревья не ближе 10 м, кустарник 1,5 м "
        "(743-ПП, табл. 3.6.1). Назначения зданий в топоплане нет."
    )
    return (*features, *schools), note


def _confirmed(outline: shapely.Geometry, near: Sequence[Feature]) -> list[int]:
    """Индексы зданий из near, которые подтверждают контур OSM."""
    areas = [i for i, b in enumerate(near) if b.geometry.area > 0]
    for i in areas:
        shared = near[i].geometry.intersection(outline).area
        if shared >= MIN_SHARE * min(near[i].geometry.area, outline.area):
            return [i]
    walls = [i for i, b in enumerate(near) if b.geometry.area == 0]
    if not walls:
        return []
    perimeter = outline.exterior
    lines = shapely.union_all([near[i].geometry for i in walls])
    covered = perimeter.intersection(lines.buffer(WALL_GAP_M)).length
    if covered >= MIN_SHARE * perimeter.length:
        return [i for i in walls if near[i].geometry.distance(perimeter) <= WALL_GAP_M]
    return []
