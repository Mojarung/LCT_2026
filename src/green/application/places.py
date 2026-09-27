"""Место посадки: у проезжей части, улица, двор, сквер, парк или «не определено».

Заказчик: «сначала тип территории и функция: аллея привязана к дороге и многоярусна, во дворе
аллей нет, свои правила у магистралей, улиц, дворов, парков» (docs/notes/15, вопрос 15).
Место задаёт категорию насаждений по МГСН 1.02-02, табл. В.6 (подбор вида, проверка плана,
индекс) и запрещает аллею во дворе.

Источники по порядку:

1. слой функционального зонирования (ГИС, классы territory.*): вид зоны по словам атрибутов;
2. полигоны проезжей части (класс road): двор - между посадкой и ближайшей проезжей частью
   стоит здание; у проезжей части - ближе ROADSIDE_M; иначе улица;
3. иначе «не определено», категория - из профиля.

Проезжую часть из бортов не выводим: проверка 27.09.2026 на четырёх улицах с полигонами
проектировщика дала совпадение места посадки лишь у 42-75% посадок (docs/plans/
2026-09-27-street-effect-design.md, п. 2.2). В геоподоснове Мосгеотреста проезжая часть
контуром не выделена; полигоны есть в слоях проекта покрытий (5 улиц пилота из 16).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature
    from green.domain.planting import Plan

ROADSIDE_M = 10.0  # ближе к проезжей части - посадка у проезжей части


class Place(StrEnum):
    ROADSIDE = "roadside"
    STREET = "street"
    YARD = "yard"
    SQUARE = "square"
    PARK = "park"
    UNKNOWN = "unknown"


PLACE_LABELS = {
    Place.ROADSIDE: "у проезжей части",
    Place.STREET: "озеленение улицы",
    Place.YARD: "двор",
    Place.SQUARE: "сквер, бульвар",
    Place.PARK: "парк",
    Place.UNKNOWN: "место не определено",
}
# Категория насаждений МГСН 1.02-02, табл. В.6 (ключи species.yaml categories).
_CATEGORY = {
    Place.ROADSIDE: "streets",
    Place.STREET: "streets",
    Place.YARD: "yards",
    Place.SQUARE: "squares",
    Place.PARK: "parks",
}
_ZONES = {
    ObjectClass.TERRITORY_YARD: Place.YARD,
    ObjectClass.TERRITORY_SQUARE: Place.SQUARE,
    ObjectClass.TERRITORY_PARK: Place.PARK,
    ObjectClass.TERRITORY_STREET: Place.STREET,
}


def category_of(place: str, default: str) -> str:
    """Категория В.6 места посадки; место не определено - категория профиля."""
    try:
        return _CATEGORY.get(Place(place), default)
    except ValueError:
        return default


@dataclass(frozen=True, slots=True)
class PlaceMap:
    source: str  # zoning | road | none
    zones: tuple[tuple[Place, BaseGeometry], ...] = ()
    road: BaseGeometry | None = None
    buildings: BaseGeometry | None = None

    def of(self, xy: NDArray[np.float64]) -> list[Place]:
        result = [Place.UNKNOWN] * len(xy)
        if not len(xy) or self.source == "none":
            return result
        points = shapely.points(np.asarray(xy, dtype=np.float64).reshape(-1, 2))
        for place, geometry in self.zones:
            inside = shapely.contains(geometry, points)
            for i in np.flatnonzero(inside).tolist():
                if result[i] is Place.UNKNOWN:
                    result[i] = place
        if self.road is None:
            return result
        open_ = [i for i, p in enumerate(result) if p in {Place.UNKNOWN, Place.STREET}]
        if not open_:
            return result
        chosen = points[open_]
        distance = shapely.distance(chosen, self.road)
        hidden = (
            shapely.intersects(shapely.shortest_line(chosen, self.road), self.buildings)
            if self.buildings is not None
            else np.zeros(len(chosen), dtype=bool)
        )
        for k, i in enumerate(open_):
            zoned = result[i] is Place.STREET
            if distance[k] <= ROADSIDE_M:
                result[i] = Place.ROADSIDE
            elif hidden[k] and not zoned:
                result[i] = Place.YARD
            else:
                result[i] = Place.STREET
        return result


# Карта мест одного чертежа: её строят и сценарий, и каждая стратегия портфеля. Ключ - сам
# кортеж объектов (id и ссылка держат его живым), одна запись - один прогон за раз.
_LAST: list[tuple[Sequence[Feature], PlaceMap]] = []


def place_map(features: Sequence[Feature]) -> PlaceMap:
    # Одно чтение записи: параллельный прогон мог заменить её между проверкой и возвратом.
    last = _LAST[0] if _LAST else None
    if last is not None and last[0] is features:
        return last[1]
    built = _build(features)
    _LAST[:] = [(features, built)]
    return built


def forget_places() -> None:
    """Прогон закончен: объекты чертежа карте мест больше не нужны."""
    _LAST.clear()


def _build(features: Sequence[Feature]) -> PlaceMap:
    zones = tuple(
        (_ZONES[f.object_class], f.geometry)
        for f in features
        if f.object_class in _ZONES and f.geometry.area > 0
    )
    roads = [
        f.geometry for f in features if f.object_class is ObjectClass.ROAD and f.geometry.area > 0
    ]
    walls = [f.geometry for f in features if f.object_class is ObjectClass.BUILDING]
    road = shapely.union_all(roads) if roads else None
    buildings = shapely.union_all(walls) if walls else None
    if road is not None:
        shapely.prepare(road)
    if buildings is not None:
        shapely.prepare(buildings)
    source = "zoning" if zones else "road" if road is not None else "none"
    return PlaceMap(source=source, zones=zones, road=road, buildings=buildings)


def with_places(plan: Plan, places: PlaceMap) -> Plan:
    """Место каждой посадке, у которой его ещё нет."""
    open_ = [i for i, p in enumerate(plan.placements) if not p.place]
    if not open_:
        return plan
    xy = np.array([(plan.placements[i].x, plan.placements[i].y) for i in open_])
    found = places.of(xy)
    placements = list(plan.placements)
    for i, place in zip(open_, found, strict=True):
        placements[i] = replace(placements[i], place=place.value)
    return replace(plan, placements=tuple(placements))


__all__ = [
    "PLACE_LABELS",
    "ROADSIDE_M",
    "Place",
    "PlaceMap",
    "category_of",
    "forget_places",
    "place_map",
    "with_places",
]
