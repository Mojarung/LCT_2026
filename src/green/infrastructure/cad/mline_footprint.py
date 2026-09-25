"""Conservative footprint of MLINE strokes and fill; never inferred terrain."""

from __future__ import annotations

import math

from ezdxf.entities import Arc, Circle, Line, MLine
from ezdxf.entities.polygon import DXFPolygon
from ezdxf.math import Vec3
from shapely.geometry import Polygon, box

from green.infrastructure.cad.hatch_footprint import bounded_hatch_footprint


def bounded_mline_footprint(  # noqa: C901, PLR0911 - reject any unsupported visible part
    entity: MLine, reserve: float
) -> Polygon | None:
    """Enclose all supported rendered parts, including space between parallel strokes."""
    if not math.isfinite(reserve) or reserve <= 0:
        return None
    xs: list[float] = []
    ys: list[float] = []

    def add(point: Vec3) -> None:
        xs.append(point.x)
        ys.append(point.y)

    try:
        for part in entity.virtual_entities():
            if isinstance(part, Line):
                add(Vec3(part.dxf.start))
                add(Vec3(part.dxf.end))
            elif isinstance(part, Arc | Circle):
                radius = abs(part.dxf.radius)
                if not math.isfinite(radius) or radius <= 0:
                    return None
                ocs = part.ocs()
                origin = ocs.to_wcs(Vec3(0, 0, 0))
                center = ocs.to_wcs(part.dxf.center)
                x_axis = ocs.to_wcs(Vec3(1, 0, 0)) - origin
                y_axis = ocs.to_wcs(Vec3(0, 1, 0)) - origin
                dx = radius * math.hypot(x_axis.x, y_axis.x)
                dy = radius * math.hypot(x_axis.y, y_axis.y)
                xs.extend((center.x - dx, center.x + dx))
                ys.extend((center.y - dy, center.y + dy))
            elif isinstance(part, DXFPolygon) and part.dxftype() == "HATCH":
                footprint = bounded_hatch_footprint(part, reserve)
                if footprint is None:
                    return None
                x0, y0, x1, y1 = footprint.bounds
                xs.extend((x0, x1))
                ys.extend((y0, y1))
            else:
                return None
    except ArithmeticError, AttributeError, TypeError, ValueError, OverflowError:
        return None
    if not xs or not all(math.isfinite(value) for value in (*xs, *ys)):
        return None
    extent = max(abs(value) for value in (*xs, *ys))
    margin = max(reserve, 64 * math.ulp(extent))
    coords = (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)
    if not all(math.isfinite(value) for value in coords):
        return None
    footprint = box(*coords)
    return footprint if footprint.is_valid and math.isfinite(footprint.area) else None
