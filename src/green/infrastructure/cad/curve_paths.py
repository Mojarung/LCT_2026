"""Curve sampling with an explicit distance bound in drawing coordinates."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from ezdxf.entities import Circle, LWPolyline

if TYPE_CHECKING:
    from ezdxf.entities import Ellipse, Polyline

MAX_VERTICES = 100_000


def ellipse_vertices(entity: Ellipse, distance: float) -> tuple[list[tuple[float, float]], bool]:
    tool = entity.construction_tool()
    # Linear interpolation error <= max|p''(t)| * h^2 / 8. The major semi-axis
    # bounds |p''| in WCS; orthogonal projection to XY cannot increase error.
    maximum = max(tool.major_axis.magnitude, tool.minor_axis.magnitude)
    count = max(8, math.ceil(tool.param_span * math.sqrt(maximum / (8 * distance))))
    if count > MAX_VERTICES:
        raise ValueError("Curve vertex budget exceeded")
    vertices = tool.vertices(
        np.linspace(tool.start_param, tool.start_param + tool.param_span, count + 1)
    )
    points = [(v.x, v.y) for v in vertices]
    closed = math.isclose(tool.param_span, math.tau, abs_tol=1e-12)
    return points, closed


def polyline_vertices(
    entity: LWPolyline | Polyline, distance: float
) -> tuple[list[tuple[float, float]], float]:
    """Bulges are circular arcs, sampled directly without a cubic approximation."""
    anchors = list(
        entity.vertices_in_wcs() if isinstance(entity, LWPolyline) else entity.points_in_wcs()
    )
    if not anchors:
        return [], 0.0
    points = [anchors[0]]
    error = 0.0
    for edge in entity.virtual_entities():
        if isinstance(edge, Circle):
            tolerance = min(distance, abs(edge.dxf.radius) / 64)
            vertices = list(edge.flattening(tolerance))
            error = max(error, tolerance)
        elif edge.dxftype() == "LINE":
            vertices = [edge.dxf.start, edge.dxf.end]
        else:
            raise TypeError("Unsupported polyline edge")
        # A negative bulge produces a reversed CCW ARC. Match the source order.
        if points[-1].distance(vertices[-1]) < points[-1].distance(vertices[0]):
            vertices.reverse()
        if not points[-1].isclose(vertices[0], rel_tol=0, abs_tol=1e-7):
            raise ValueError("Disconnected polyline edges")
        points.extend(vertices[1:])
        if len(points) > MAX_VERTICES:
            raise ValueError("Curve vertex budget exceeded")
    return [(v.x, v.y) for v in points], error
