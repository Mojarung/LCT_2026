"""Подоснова для отрисовки плана в браузере.

Канва не может принять чертёж целиком: на генплане 309 тыс. сущностей. Отбираем то, что
на карте видно и что объясняет посадку (сети, борта, покрытия, здания, газоны), и упрощаем
геометрию. Рядом с тем, что осталось, обязательно едет то, что отброшено и почему: карта,
показывающая только выход, не отличает осмысленный отбор от молчаливой потери.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import shapely
from shapely.errors import GEOSException

from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature

# Классы, которым на карте нечего делать: «ignore» отсеян классификатором намеренно,
# «unknown» - это подписи, штриховки и условные знаки, не несущие нормативного смысла.
HIDDEN_CLASSES = frozenset({ObjectClass.IGNORE, ObjectClass.UNKNOWN})

DEGENERATE = "вырождено упрощением"
EMPTY = "пустая геометрия"

DEFAULT_TOLERANCE_M = 0.15
# Сантиметр. Геоподоснова точнее не бывает, а координата с семнадцатью знаками после запятой
# утраивает вес выгрузки: на Берзарина 33,6 МБ против 12,9 МБ при той же геометрии.
DEFAULT_PRECISION_M = 0.01


@dataclass(frozen=True, slots=True)
class BasemapFeature:
    """Объект подосновы в координатах чертежа (метры), готовый к отрисовке."""

    object_class: ObjectClass
    geometry: BaseGeometry


@dataclass(frozen=True, slots=True)
class Basemap:
    """Подоснова для карты вместе с балансом отбора.

    features_out + сумма dropped всегда равна features_in: это инвариант, по которому
    видно потерю. Если равенство нарушилось - потерялся объект, а не изменился формат.
    """

    features: tuple[BasemapFeature, ...]
    features_in: int
    features_out: int
    dropped: Mapping[str, int]
    bbox: tuple[float, float, float, float]


def build_basemap(
    features: Sequence[Feature],
    *,
    tolerance_m: float = DEFAULT_TOLERANCE_M,
    precision_m: float = DEFAULT_PRECISION_M,
) -> Basemap:
    """Отобрать и упростить подоснову для отрисовки на канве.

    На вход идут объекты уже после классификации и присвоения диаметров - те же, по которым
    считался план: карта обязана показывать ту подоснову, на которой стоят отступы.
    """
    kept: list[BasemapFeature] = []
    dropped: Counter[str] = Counter()

    for feature in features:
        if feature.object_class in HIDDEN_CLASSES:
            dropped[feature.object_class.value] += 1
            continue
        geometry = feature.geometry
        if geometry is None or geometry.is_empty:
            dropped[EMPTY] += 1
            continue
        simplified = geometry.simplify(tolerance_m, preserve_topology=True)
        if precision_m > 0:
            simplified = _snap(simplified, precision_m)
        if _is_degenerate(simplified, tolerance_m):
            dropped[DEGENERATE] += 1
            continue
        kept.append(BasemapFeature(object_class=feature.object_class, geometry=simplified))

    return Basemap(
        features=tuple(kept),
        features_in=len(features),
        features_out=len(kept),
        dropped=dict(dropped),
        bbox=_bbox(kept),
    )


def _snap(geometry: BaseGeometry, precision_m: float) -> BaseGeometry:
    """Посадить координаты на сантиметровую сетку, чтобы в JSON шли короткие числа.

    GEOS на снятии точности иногда роняет вырожденные объекты в пустую геометрию: это
    нормально, их отсеет проверка ниже. Отказ операции не должен ронять весь прогон, поэтому
    при исключении возвращаем исходную геометрию - длинные координаты лучше, чем нет карты.
    """
    try:
        snapped = shapely.set_precision(geometry, precision_m)
    except GEOSException, ValueError:
        return geometry
    return geometry if snapped.is_empty and not geometry.is_empty else snapped


def _is_degenerate(geometry: BaseGeometry, tolerance_m: float) -> bool:
    """Объект, который на карте займёт меньше допуска упрощения, рисовать нечем.

    Точка не вырождается никогда: опора, колодец и существующее дерево - это точки,
    и именно от них считаются отступы.
    """
    if geometry.is_empty:
        return True
    if geometry.geom_type in {"Point", "MultiPoint"}:
        return False
    if geometry.area > 0:
        return geometry.area < tolerance_m * tolerance_m
    return geometry.length < tolerance_m


def _bbox(features: list[BasemapFeature]) -> tuple[float, float, float, float]:
    if not features:
        return (0.0, 0.0, 0.0, 0.0)
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")
    for feature in features:
        left, bottom, right, top = feature.geometry.bounds
        min_x = min(min_x, left)
        min_y = min(min_y, bottom)
        max_x = max(max_x, right)
        max_y = max(max_y, top)
    return (min_x, min_y, max_x, max_y)
