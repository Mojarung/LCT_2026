"""Граница работ, когда чертёж её не даёт.

Без границы работ размещение было заблокировано: план пуст, хотя подоснова прочитана. Чужой
чертёж (выгрузка паспорта ОГХ, топоплан без слоя заказа, всё на слое 0) границы часто не несёт
или несёт незамкнутой. Тогда участок берётся из самого чертежа, и прогон говорит об этом:

- граница работ нарисована, но не замкнута (разрыв шире 5 м) - выпуклая оболочка её линий;
- границы нет - выпуклая оболочка объектов подосновы. Узнанные классы важнее неопознанных;
  оформление, контуры рельефа и зоны ГИС участок не задают, а одиночный объект далеко от
  остальных (вставка у начала координат) отбрасывается по разбросу центров.

Посадки по такой границе проходят все проверки норм, как обычно; граница - допущение, её можно
задать слоем (layer_classes) или отключить вывод (infer_work_boundary=false).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.application.constraints import work_boundary
from green.domain.objects import Feature, ObjectClass, SourceRef

if TYPE_CHECKING:
    from collections.abc import Sequence

    from shapely.geometry.base import BaseGeometry

INFERRED_LAYER = "Граница работ (принята по чертежу)"
INFERRED_REF = SourceRef("inferred", "00000000", "work_area")
MIN_AREA_M2 = 100.0  # меньше - сажать негде, граница не выводится
# Далёкая одиночка - центр дальше SPREAD_FENCE медианных расстояний от медианной точки и
# дальше SPREAD_KEEP_M: чужая вставка (у начала координат, на другом листе), а не участок.
# Медиана, а не квартили по осям: у улицы большинство объектов - борта на одной линии.
SPREAD_FENCE = 3.0
SPREAD_KEEP_M = 500.0
_CORE_MIN = 20  # меньше объектов - разброс не оценивается
_NOT_SITE = frozenset({ObjectClass.IGNORE, ObjectClass.CONTOUR, ObjectClass.WORK_BOUNDARY})
_M2_PER_HA = 10_000.0


def with_work_area(features: Sequence[Feature]) -> tuple[tuple[Feature, ...], str | None]:
    """Объекты чертежа с выведенной границей работ и пояснение для журнала прогона.

    Граница чертежа есть и замкнута - объекты возвращаются как есть, пояснения нет."""
    features = tuple(features)
    if work_boundary(features) is not None:
        return features, None
    drawn = [f for f in features if f.object_class is ObjectClass.WORK_BOUNDARY]
    hull, source = _hull(drawn), "по незамкнутой границе работ чертежа (выпуклая оболочка)"
    if hull is None:
        site = [f for f in features if _is_site(f)]
        known = [f for f in site if f.object_class is not ObjectClass.UNKNOWN]
        everything = [f for f in features if f.object_class is not ObjectClass.WORK_BOUNDARY]
        chosen = known or site or everything
        hull = _hull(_core(chosen))
        kind = "узнанных объектов" if known else "объектов"
        source = f"по охвату {kind} подосновы (выпуклая оболочка, {len(chosen)} шт.)"
    if hull is None:
        return features, None
    area = Feature(
        ref=INFERRED_REF,
        layer=INFERRED_LAYER,
        geometry=shapely.LineString(hull.exterior.coords),
        object_class=ObjectClass.WORK_BOUNDARY,
        source_entity_type="INFERRED",
    )
    hectares = f"{hull.area / _M2_PER_HA:.2f}".replace(".", ",")
    note = (
        f"Исправлено автоматически: замкнутой границы работ в чертеже нет - участок принят "
        f"{source}, {hectares} га. Посадки проверены по всем нормам как обычно; чтобы задать "
        "участок точно, назначьте слой границы работ (layer_classes: <слой>: work_boundary) "
        "или запустите с infer_work_boundary=false."
    )
    return (*features, area), note


def _is_site(feature: Feature) -> bool:
    value = feature.object_class.value
    return feature.object_class not in _NOT_SITE and not value.startswith(("territory.", "zone."))


def _core(features: Sequence[Feature]) -> list[Feature]:
    """Объекты без далёких одиночек (SPREAD_FENCE, SPREAD_KEEP_M)."""
    if len(features) < _CORE_MIN:
        return list(features)
    centres = shapely.get_coordinates(shapely.centroid([f.geometry for f in features]))
    if len(centres) != len(features):  # пустая геометрия не даёт центра
        return list(features)
    distance = np.hypot(*(centres - np.median(centres, axis=0)).T)
    keep = distance <= max(SPREAD_FENCE * float(np.median(distance)), SPREAD_KEEP_M)
    return [f for f, k in zip(features, keep, strict=True) if k]


def _hull(features: Sequence[Feature]) -> BaseGeometry | None:
    geometries = [f.geometry for f in features if not f.geometry.is_empty]
    if not geometries:
        return None
    hull = shapely.convex_hull(shapely.GeometryCollection(geometries))
    if hull.geom_type != "Polygon" or hull.area < MIN_AREA_M2:
        return None
    return hull
