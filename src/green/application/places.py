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

Полигоны проезжей части в чертежах пилота - слои проекта покрытий: часто участки ремонта
покрытия и уширений, а не вся проезжая часть. «Двор» и «улица» выводятся из того, что ближайшая
проезжая часть известна; если она не нарисована, здание между посадкой и далёким участком
ремонта двора не доказывает (Измайловская площадь, 28.09.2026: один полигон «ПЧ за газон» меньше
квадратного метра делал двором 597 посадок из 843 и снимал там места аллеи). Поэтому:

- полигон меньше MIN_ROAD_M2 - обрезок, не проезжая часть;
- если вдоль полигонов (ближе CURB_ON_ROAD_M к их краю) лежит меньше ROAD_COVERAGE_MIN
  длины бортов участка, полигоны неполные: «у проезжей части» остаётся (известная проезжая
  часть рядом), остальное - «не определено» (источник road-partial). По подоснове улиц пилота
  доля на реальных бортах: Олимпийская деревня 37% (заливка проезжей части, но много
  внутренних бортов у тротуаров и газонов - осторожно «не определено»), Берзарина и
  Харьковский проезд - не меньше половины; часть бортов - садовые, поэтому и полная
  проезжая часть не даёт 100%.

Проезжую часть из бортов не выводим: проверка 27.09.2026 на четырёх улицах с полигонами
проектировщика дала совпадение места посадки лишь у 42-75% посадок (docs/plans/
2026-09-27-street-effect-design.md, п. 2.2). В геоподоснове Мосгеотреста проезжая часть
контуром не выделена; полигоны есть в слоях проекта покрытий (5 улиц пилота из 16).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any

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
MIN_ROAD_M2 = 20.0  # меньше - обрезок полигона, а не проезжая часть
CURB_ON_ROAD_M = 3.0  # борт ближе к краю полигона - борт этой проезжей части
ROAD_COVERAGE_MIN = 0.5  # доля бортов вдоль полигонов, при которой полигоны считаются полными


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
    source: str  # zoning | road | road-partial | none
    zones: tuple[tuple[Place, BaseGeometry], ...] = ()
    road: BaseGeometry | None = None
    buildings: BaseGeometry | None = None
    # Полигоны проезжей части закрывают её целиком: без этого «двор» и «улица» не выводятся.
    complete: bool = True
    # Доля бортов участка вдоль полигонов проезжей части; None - бортов нет или полигонов нет.
    coverage: float | None = None

    @property
    def note(self) -> str:
        """Почему место посадки определено не везде - для предупреждений прогона."""
        if self.source != "road-partial":
            return ""
        share = f"{round((self.coverage or 0.0) * 100)}%"
        # Без догадки о причине: на улицах пилота это то участки ремонта покрытия, то заливка
        # всей проезжей части в районе с множеством внутренних бортов (Олимпийская деревня, 37%).
        return (
            f"Место посадки: вдоль полигонов проезжей части лежит {share} бортов участка - меньше "
            "половины, и по чертежу не видно, нарисована ли проезжая часть целиком. Отмечены "
            "посадки у проезжей части; двор и улица не определены, категория насаждений - из "
            "профиля."
        )

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
        if self.road is not None:
            self._by_road(result, points, self.road)
        return result

    def _by_road(self, result: list[Place], points: NDArray[Any], road: BaseGeometry) -> None:
        """У проезжей части, двор или улица - для посадок без места или с местом «улица» по
        зонированию (зонирование двора не отменяет)."""
        open_ = [i for i, p in enumerate(result) if p in {Place.UNKNOWN, Place.STREET}]
        if not open_:
            return
        chosen = points[open_]
        distance = shapely.distance(chosen, road)
        hidden = (
            shapely.intersects(shapely.shortest_line(chosen, road), self.buildings)
            if self.buildings is not None and self.complete
            else np.zeros(len(chosen), dtype=bool)
        )
        for k, i in enumerate(open_):
            zoned = result[i] is Place.STREET
            if distance[k] <= ROADSIDE_M:
                result[i] = Place.ROADSIDE
            elif not self.complete:
                continue  # далёкая проезжая часть не нарисована: двор и улица не доказаны
            elif hidden[k] and not zoned:
                result[i] = Place.YARD
            else:
                result[i] = Place.STREET


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
        f.geometry
        for f in features
        if f.object_class is ObjectClass.ROAD and f.geometry.area >= MIN_ROAD_M2
    ]
    walls = [f.geometry for f in features if f.object_class is ObjectClass.BUILDING]
    road = shapely.union_all(roads) if roads else None
    buildings = shapely.union_all(walls) if walls else None
    coverage = None if road is None else _curb_coverage(road, features)
    complete = coverage is None or coverage >= ROAD_COVERAGE_MIN
    if road is not None:
        shapely.prepare(road)
    if buildings is not None:
        shapely.prepare(buildings)
    source = (
        "zoning" if zones else "none" if road is None else "road" if complete else "road-partial"
    )
    return PlaceMap(
        source=source,
        zones=zones,
        road=road,
        buildings=buildings,
        complete=complete,
        coverage=coverage,
    )


def _curb_coverage(road: BaseGeometry, features: Sequence[Feature]) -> float | None:
    """Доля длины бортов участка (внутри границы работ, если она есть), лежащей ближе
    CURB_ON_ROAD_M к краю полигонов проезжей части. Бортов нет - проверить нечем (None),
    полигоны принимаются как есть."""
    curbs = [f.geometry for f in features if f.object_class is ObjectClass.CURB]
    if not curbs:
        return None
    curb = shapely.union_all(curbs)
    bounds = [
        f.geometry
        for f in features
        if f.object_class is ObjectClass.WORK_BOUNDARY and f.geometry.area > 0
    ]
    if bounds:
        curb = curb.intersection(shapely.union_all(bounds))
    total = curb.length
    if total <= 0:
        return None
    return float(curb.intersection(road.boundary.buffer(CURB_ON_ROAD_M)).length / total)


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


def replace_moved_places(before: Plan, after: Plan, places: PlaceMap) -> Plan:
    """Посадки, сдвинутые после размещения (сдвиг слабых мест): место в новой точке заново."""
    was = {p.placement_id: (p.x, p.y) for p in before.placements}
    cleared = tuple(
        replace(p, place="") if was.get(p.placement_id) not in {None, (p.x, p.y)} else p
        for p in after.placements
    )
    return with_places(replace(after, placements=cleared), places)


__all__ = [
    "MIN_ROAD_M2",
    "PLACE_LABELS",
    "ROADSIDE_M",
    "ROAD_COVERAGE_MIN",
    "Place",
    "PlaceMap",
    "category_of",
    "forget_places",
    "place_map",
    "replace_moved_places",
    "with_places",
]
