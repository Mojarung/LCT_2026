"""Bound an invalid closed polyline without choosing a fill for its crossings."""

from __future__ import annotations

import math

from shapely.geometry import Polygon, box


def bounded_invalid_polyline(
    geometry: Polygon, curve_error: float, reserve: float
) -> Polygon | None:
    """The filled region cannot extend outside the boundary's buffered XY bounds."""
    if (
        geometry.is_empty
        or geometry.is_valid
        or not math.isfinite(curve_error)
        or curve_error < 0
        or not math.isfinite(reserve)
        or reserve <= 0
    ):
        return None
    x0, y0, x1, y1 = geometry.bounds
    values = (x0, y0, x1, y1)
    if not all(math.isfinite(value) for value in values):
        return None
    margin = max(curve_error, reserve, 64 * math.ulp(max(abs(value) for value in values)))
    expanded = (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    if not all(math.isfinite(value) for value in expanded):
        return None
    footprint = box(*expanded)
    return footprint if footprint.is_valid and math.isfinite(footprint.area) else None
