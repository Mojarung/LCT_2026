"""Accept only topology repairs that preserve a polygon's measured boundary."""

from __future__ import annotations

import math

import shapely
from shapely.errors import GEOSException
from shapely.geometry import Polygon

_MAX_BOUNDARY_SHIFT = 1e-9
_MAX_AREA_SHIFT = 1e-9


def repair_roundoff_self_intersection(polygon: Polygon) -> Polygon | None:
    """Keep a repaired ring only if neither its boundary nor its area moves materially.

    ACIS and HATCH sometimes describe a zero-width overlap between two edges.
    ``make_valid`` retains that edge as the boundary of a tiny interior ring. A
    bow tie, crossing, or other ambiguous footprint fails the checks below.
    """
    if polygon.is_valid or polygon.is_empty or polygon.area <= 0:
        return None
    try:
        repaired = shapely.make_valid(polygon)
        if not isinstance(repaired, Polygon):
            return None
        acceptable = (
            not repaired.is_empty
            and repaired.is_valid
            and math.isfinite(repaired.area)
            and repaired.area > 0
            and abs(repaired.area - polygon.area) <= _MAX_AREA_SHIFT
            and polygon.boundary.hausdorff_distance(repaired.boundary) <= _MAX_BOUNDARY_SHIFT
            and polygon.symmetric_difference(repaired).area <= _MAX_AREA_SHIFT
        )
    except GEOSException:
        return None
    return repaired if acceptable else None
