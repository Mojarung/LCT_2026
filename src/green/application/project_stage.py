"""Проектные изменения поверх топосъёмки: старая граница покрытия внутри проектного газона.

Проект заменяет часть твёрдых покрытий газоном («Газон за счёт АБ», «Газон на месте плитки»), а
линия съёмки на месте бывшего края тротуара остаётся в подоснове и продолжает требовать 0,7 м.
Аудит Берзарина 16.10.2026: 48 из 49 срабатываний «край тротуара» - такие линии. Внутри
объединённого газона (соседние штриховки - один газон) глубже EDGE_INSIDE_LAWN_M граница
покрытия - не край существующего покрытия, а след прежнего состояния: она снимается. Борт не
трогается: садовый борт клумбы внутри газона - настоящий объект.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import shapely

from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature

EDGE_INSIDE_LAWN_M = 0.15  # глубже внутрь газона - линия не его край
MIN_PIECE_M = 0.5


def drop_edges_inside_lawn(features: Sequence[Feature]) -> tuple[tuple[Feature, ...], int]:
    """Объекты без частей границ покрытия внутри газона и число затронутых линий."""
    lawns = [
        f.geometry for f in features if f.object_class is ObjectClass.LAWN and f.geometry.area > 0
    ]
    if not lawns:
        return tuple(features), 0
    inner = shapely.union_all(lawns).buffer(-EDGE_INSIDE_LAWN_M)
    if inner.is_empty:
        return tuple(features), 0
    shapely.prepare(inner)
    out: list[Feature] = []
    touched = 0
    for feature in features:
        if feature.object_class is not ObjectClass.PAVEMENT_EDGE or not inner.intersects(
            feature.geometry
        ):
            out.append(feature)
            continue
        rest = _lines(feature.geometry.difference(inner))
        touched += 1
        if rest.length >= MIN_PIECE_M:
            out.append(replace(feature, geometry=rest))
    return tuple(out), touched


def _lines(geometry: BaseGeometry) -> BaseGeometry:
    pieces = [
        part
        for part in shapely.get_parts(geometry)
        if part.geom_type in {"LineString", "MultiLineString"} and part.length > 0
    ]
    return shapely.line_merge(shapely.union_all(pieces)) if pieces else shapely.LineString()
