"""Conservative XY bounds for malformed HATCH made of analytic CAD edges.

This is an uncertainty footprint, never a reconstruction of the filled area.
Unsupported edge types leave the HATCH as a blocking import gap.
"""

from __future__ import annotations

import math
from itertools import pairwise
from typing import TYPE_CHECKING

import shapely
from ezdxf.entities.boundary_paths import ArcEdge, EdgePath, EllipseEdge, LineEdge, PolylinePath
from ezdxf.math import Vec3, bulge_center, bulge_radius
from shapely.errors import GEOSException
from shapely.geometry import Polygon, box

from green.infrastructure.cad.hatch_geometry import (
    HatchGeometryError,
    _checked_ring,
    _path_polygon,
)

if TYPE_CHECKING:
    from ezdxf.entities.polygon import DXFPolygon


class _Bounds:
    def __init__(self, hatch: DXFPolygon) -> None:
        ocs = hatch.ocs()
        elevation = hatch.dxf.elevation.z
        self.origin = ocs.to_wcs(Vec3(0, 0, elevation))
        self.x_axis = ocs.to_wcs(Vec3(1, 0, 0))
        self.y_axis = ocs.to_wcs(Vec3(0, 1, 0))
        self.values_x: list[float] = []
        self.values_y: list[float] = []

    def point(self, x: float, y: float) -> None:
        point = self.origin + self.x_axis * x + self.y_axis * y
        self.values_x.append(point.x)
        self.values_y.append(point.y)

    def ellipse(self, x: float, y: float, major_x: float, major_y: float, ratio: float) -> None:
        if ratio <= 0:
            raise ValueError("Invalid ellipse ratio")
        center = self.origin + self.x_axis * x + self.y_axis * y
        major = self.x_axis * major_x + self.y_axis * major_y
        minor = (self.x_axis * -major_y + self.y_axis * major_x) * ratio
        span_x = math.hypot(major.x, minor.x)
        span_y = math.hypot(major.y, minor.y)
        self.values_x.extend((center.x - span_x, center.x + span_x))
        self.values_y.extend((center.y - span_y, center.y + span_y))

    def circle(self, x: float, y: float, radius: float) -> None:
        if radius <= 0:
            raise ValueError("Invalid circle radius")
        self.ellipse(x, y, radius, 0, 1.0)

    def polygon(self, reserve: float) -> Polygon | None:
        values = (*self.values_x, *self.values_y)
        if not values or not all(math.isfinite(value) for value in values):
            return None
        extent = max(abs(value) for value in values)
        margin = max(reserve, 64 * math.ulp(extent))
        return box(
            min(self.values_x) - margin,
            min(self.values_y) - margin,
            max(self.values_x) + margin,
            max(self.values_y) + margin,
        )


def _polyline(bounds: _Bounds, path: PolylinePath) -> None:
    vertices = path.vertices
    if not vertices:
        raise ValueError("Empty polyline HATCH path")
    for x, y, _ in vertices:
        bounds.point(x, y)
    edges = list(pairwise(vertices))
    if path.is_closed or vertices[-1][2]:
        edges.append((vertices[-1], vertices[0]))
    for first, second in edges:
        x0, y0, bulge = first
        if bulge:
            center = bulge_center((x0, y0), second[:2], bulge)
            radius = bulge_radius((x0, y0), second[:2], bulge)
            bounds.circle(center.x, center.y, radius)


def _edges(bounds: _Bounds, path: EdgePath) -> bool:
    if not path.edges:
        return False
    for edge in path.edges:
        if isinstance(edge, LineEdge):
            bounds.point(edge.start.x, edge.start.y)
            bounds.point(edge.end.x, edge.end.y)
        elif isinstance(edge, ArcEdge):
            bounds.circle(edge.center.x, edge.center.y, edge.radius)
        elif isinstance(edge, EllipseEdge):
            bounds.ellipse(
                edge.center.x,
                edge.center.y,
                edge.major_axis.x,
                edge.major_axis.y,
                edge.ratio,
            )
        else:
            return False
    return True


def bounded_hatch_footprint(
    hatch: DXFPolygon, reserve: float
) -> Polygon | shapely.MultiPolygon | None:
    """Enclose each path's possible fill, without boxing distant loops together."""
    if not math.isfinite(reserve) or reserve <= 0 or not hatch.paths.paths:
        return None
    try:
        footprints = []
        global_bounds = _Bounds(hatch)
        for path in hatch.paths.paths:
            bounds = _Bounds(hatch)
            if isinstance(path, PolylinePath):
                _polyline(bounds, path)
                _polyline(global_bounds, path)
            elif (
                not isinstance(path, EdgePath)
                or not _edges(bounds, path)
                or not _edges(global_bounds, path)
            ):
                return None
            path_box = bounds.polygon(reserve)
            if path_box is None:
                return None
            try:
                polygon, error, _ = _path_polygon(hatch, path, reserve, reserve * 0.02)
                ring = _checked_ring(polygon)
                footprints.append(ring.buffer(reserve + error))
            except HatchGeometryError, GEOSException, ValueError:
                footprints.append(path_box)
        result = shapely.union_all(footprints)
        if result.is_valid and not result.is_empty:
            return result
        return global_bounds.polygon(reserve)
    except ArithmeticError, GEOSException, TypeError, ValueError, OverflowError:
        return None
