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

from green.application.semantic_names import base_name
from green.application.shrub_strips import SHRUB_STRIP_SOURCE
from green.application.surfaces import Material, label_material
from green.application.tree_strips import STRIP_SOURCE
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature, TextLabel

# Классы, которым на карте нечего делать: «ignore» отсеян классификатором намеренно,
# «unknown» - это подписи, штриховки и условные знаки, не несущие нормативного смысла.
HIDDEN_CLASSES = frozenset({ObjectClass.IGNORE, ObjectClass.UNKNOWN})

DEGENERATE = "вырождено упрощением"
EMPTY = "пустая геометрия"
SMALL = "мельче видимого на карте"

DEFAULT_TOLERANCE_M = 0.15
# Сантиметр. Геоподоснова точнее не бывает, а координата с семнадцатью знаками после запятой
# утраивает вес выгрузки: на Берзарина 33,6 МБ против 12,9 МБ при той же геометрии.
DEFAULT_PRECISION_M = 0.01

# Сколько объектов карта в браузере держит без потери отзывчивости (замеры в
# `docs/notes/27-map-performance.md`: 56 тыс. объектов - 110 мс на кадр, 15 тыс. - 45 мс).
# Чертёж тяжелее бюджета упрощается сильнее и теряет мелочь: на Камчатской из 56 тыс.
# объектов 40 тыс. мельче метра, это обломки условных знаков, а не сети.
FEATURE_BUDGET = 20_000
# Порог мелочи при однократном превышении бюджета; растёт вместе с допуском упрощения.
SPAN_FLOOR_M = 0.5
# Дальше этого детализацию не режем даже на генплане: подоснова должна остаться читаемой.
MAX_DETAIL_CUT = 2.0
POINT_TYPES = frozenset({"Point", "MultiPoint"})
# Знаки съёмки Мосгеотреста для хвойного дерева (config/symbols.yaml): сосна, ель, кипарисовые,
# туя. Карта рисует такое дерево знаком хвойного сохраняемого, как в дендропланах пилота
# (зелёное кольцо). Лиственница LISTVN не подтверждена рисунком и сюда не входит.
CONIFER_SYMBOLS = frozenset({"SOSNOD", "ELOD", "KIPAR", "TUYA"})


@dataclass(frozen=True, slots=True)
class BasemapFeature:
    """Объект подосновы в координатах чертежа (метры), готовый к отрисовке."""

    object_class: ObjectClass
    geometry: BaseGeometry
    # Существующее дерево со знаком хвойного (CONIFER_SYMBOLS): на карте - зелёное кольцо.
    conifer: bool = False
    vegetation_kind: str | None = None


@dataclass(frozen=True, slots=True)
class MaterialLabel:
    """Подпись материала покрытия с чертежа: «А», «ГАЗОН», «ДЕТ.ПЛ.»."""

    x: float
    y: float
    text: str
    material: str  # paved | soil


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
    # С какой детализацией собрана эта подоснова: допуск упрощения и порог отбрасывания
    # мелочи. Оба зависят от веса чертежа, поэтому едут вместе с данными, а не в коде.
    tolerance_m: float = DEFAULT_TOLERANCE_M
    min_span_m: float = 0.0
    # Подписи, по которым сервис решил, где грунт, а где покрытие. Без них на карте не видно,
    # что прямоугольник - это детская площадка со спецпокрытием, а не газон.
    labels: tuple[MaterialLabel, ...] = ()


def material_labels(labels: Sequence[TextLabel]) -> tuple[MaterialLabel, ...]:
    """Подписи, которые карта покрытий прочитала как материал."""
    found = []
    for label in labels:
        material = label_material(label.text)
        if material is not None:
            kind = "paved" if material is Material.PAVED else "soil"
            found.append(MaterialLabel(label.x, label.y, label.text.strip(), kind))
    return tuple(found)


def build_basemap(
    features: Sequence[Feature],
    labels: Sequence[TextLabel] = (),
    *,
    tolerance_m: float = DEFAULT_TOLERANCE_M,
    precision_m: float = DEFAULT_PRECISION_M,
    feature_budget: int = FEATURE_BUDGET,
) -> Basemap:
    """Отобрать и упростить подоснову для отрисовки на канве.

    На вход идут объекты уже после классификации и присвоения диаметров - те же, по которым
    считался план: карта обязана показывать ту подоснову, на которой стоят отступы.

    Детализация зависит от веса чертежа. Улица пилота даёт полсотни тысяч объектов, и карта
    в браузере на них не едет за рукой, а выгрузка весит десятки мегабайт. Поэтому чертёж
    тяжелее `FEATURE_BUDGET` упрощается грубее и теряет объекты мельче порога - те, что на
    экране не отличимы от точки. Выбранные значения едут в `Basemap` и в выгрузку: читатель
    карты должен знать, насколько она огрублена.
    """
    kept: list[BasemapFeature] = []
    dropped: Counter[str] = Counter()

    visible = sum(1 for f in features if f.object_class not in HIDDEN_CLASSES)
    cut = min(max(visible / feature_budget, 1.0) ** 0.5, MAX_DETAIL_CUT)
    tolerance_m *= cut
    min_span_m = SPAN_FLOOR_M * cut if cut > 1 else 0.0

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
        if _is_small(simplified, min_span_m):
            dropped[SMALL] += 1
            continue
        vegetation_kind = None
        if feature.object_class in {ObjectClass.EXISTING_TREE, ObjectClass.EXISTING_SHRUB}:
            vegetation_kind = (
                "shrub_strip"
                if feature.source_entity_type == SHRUB_STRIP_SOURCE
                else "strip"
                if feature.source_entity_type == STRIP_SOURCE
                else "individual"
            )
        kept.append(
            BasemapFeature(
                object_class=feature.object_class,
                geometry=simplified,
                conifer=_is_conifer(feature),
                vegetation_kind=vegetation_kind,
            )
        )

    return Basemap(
        features=tuple(kept),
        features_in=len(features),
        features_out=len(kept),
        dropped=dict(dropped),
        bbox=_bbox(kept),
        tolerance_m=round(tolerance_m, 3),
        min_span_m=round(min_span_m, 3),
        labels=material_labels(labels),
    )


def _is_conifer(feature: Feature) -> bool:
    """Существующее дерево, вставленное знаком хвойного из съёмки."""
    return (
        feature.object_class is ObjectClass.EXISTING_TREE
        and feature.block is not None
        and base_name(feature.block).upper() in CONIFER_SYMBOLS
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


def _is_small(geometry: BaseGeometry, min_span_m: float) -> bool:
    """Объект, который весь умещается в порог: на карте это точка, а места он занимает как сеть.

    Точечные объекты порогом не режутся: опора, колодец и существующее дерево - это условные
    знаки, они читаются на любом масштабе и от них считаются отступы.
    """
    if min_span_m <= 0 or geometry.geom_type in POINT_TYPES:
        return False
    left, bottom, right, top = geometry.bounds
    return max(right - left, top - bottom) < min_span_m


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
