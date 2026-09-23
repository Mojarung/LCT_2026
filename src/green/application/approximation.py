"""Conservative spatial envelopes for known XY approximation errors."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

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
