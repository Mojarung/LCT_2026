"""Conservative spatial envelopes for known XY approximation errors."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import shapely

from green.application.errors import InputError

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature

_QUADRANT_SEGMENTS = 8
# GEOS represents round buffer corners with inscribed chords. Inflate the radius
# so each chord stays at least the requested distance from the original vertex.
_BUFFER_RESERVE = 1 / math.cos(math.pi / (4 * _QUADRANT_SEGMENTS))


def error_bound(feature: Feature) -> float:
    error = feature.geometry_error_m
    if error is None or not math.isfinite(error) or error < 0:
        raise InputError(f"Не установлена погрешность геометрии объекта {feature.ref}")
    return error


def reserved_buffer(geometry: BaseGeometry, distance: float) -> BaseGeometry:
    if distance == 0:
        return geometry
    return geometry.buffer(distance * _BUFFER_RESERVE, quad_segs=_QUADRANT_SEGMENTS)


def inner_area(feature: Feature) -> BaseGeometry:
    return reserved_buffer(feature.geometry, -error_bound(feature))


def outer_area(feature: Feature) -> BaseGeometry:
    return reserved_buffer(feature.geometry, error_bound(feature))


# Буфер мультилинии из тысяч частей GEOS строит объединением буферов каждой части, и на частом
# пунктире (десятки тысяч штрихов в сантиметрах друг от друга) это минуты и часы. Те же точки
# дают два шага: тонкий буфер каждой части, объединение, затем буфер многоугольника на
# остаток расстояния (сумма Минковского кругов - круг суммы радиусов). Синтетический борт из
# 28 920 штрихов: больше 390 с напрямую, 4 с в два шага (20.10.2026).
MANY_PARTS = 2_000
THIN_M = 0.05


def buffer_lines(geometry: BaseGeometry, distance: float, *, quad_segs: int = 8) -> BaseGeometry:
    """Буфер линий на distance; для мультилинии из многих частей - в два шага."""
    parts = shapely.get_parts(geometry)
    if len(parts) < MANY_PARTS or distance <= THIN_M:
        return shapely.buffer(geometry, distance, quad_segs=quad_segs)
    thin = shapely.union_all(shapely.buffer(parts, THIN_M, quad_segs=2))
    return shapely.buffer(thin, distance - THIN_M, quad_segs=quad_segs)
