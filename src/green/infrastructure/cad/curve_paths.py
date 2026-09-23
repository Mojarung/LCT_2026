"""Curve sampling with an explicit distance bound in drawing coordinates."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from ezdxf.entities import Arc, Circle, LWPolyline
from ezdxf.math import arc_segment_count

if TYPE_CHECKING:
    from ezdxf.entities import Ellipse, Polyline
    from ezdxf.math import ConstructionArc, ConstructionEllipse, Vec2, Vec3

MAX_VERTICES = 100_000
_TURN_DEG = 360


def arc_tool_vertices(tool: ConstructionArc, distance: float) -> tuple[list[Vec2], float]:
    """Subtract angles before wrapping: normalizing endpoints can erase a full turn."""
    if not math.isfinite(tool.radius) or tool.radius <= 0:
        raise ValueError("Invalid circular radius")
    tolerance = min(distance, tool.radius / 64)
    delta = tool.end_angle - tool.start_angle
    if not math.isfinite(delta):
        raise ValueError("Invalid circular angles")
    turns = round(delta / _TURN_DEG)
    correction = abs(delta - turns * _TURN_DEG)
    rounding = 4 * (math.ulp(tool.start_angle) + math.ulp(tool.end_angle) + math.ulp(delta))
    span = delta % _TURN_DEG
    if turns and correction <= rounding:
        # CAD full turns can round to 360.00000000000006 on serialization.
        # Use a few ULPs, not a relative angular tolerance which would also
        # swallow meaningful short arcs. Reserve the endpoint displacement.
        span = _TURN_DEG
    if span == 0:
        return [], tolerance
    count = arc_segment_count(tool.radius, math.radians(span), tolerance)
    if count > MAX_VERTICES:
        raise ValueError("Curve vertex budget exceeded")
    start = tool.start_angle % _TURN_DEG
    error = tolerance + (
        tool.radius * math.radians(correction) if turns and span == _TURN_DEG else 0
    )
    return list(tool.vertices(np.linspace(start, start + span, count + 1))), error


def circle_vertices(entity: Circle, distance: float) -> tuple[list[Vec3], float]:
    if isinstance(entity, Arc):
        vertices, tolerance = arc_tool_vertices(entity.construction_tool(), distance)
        ocs, elevation = entity.ocs(), entity.dxf.center.z
        return [ocs.to_wcs((v.x, v.y, elevation)) for v in vertices], tolerance
    radius = abs(entity.dxf.radius)
    if not math.isfinite(radius) or radius == 0:
        raise ValueError("Invalid circular radius")
    tolerance = min(distance, radius / 64)
    count = arc_segment_count(radius, math.tau, tolerance)
    if count > MAX_VERTICES:
        raise ValueError("Curve vertex budget exceeded")
    return list(entity.vertices(np.linspace(0, 360, count + 1))), tolerance


def ellipse_vertices(entity: Ellipse, distance: float) -> tuple[list[tuple[float, float]], bool]:
    return ellipse_tool_vertices(entity.construction_tool(), distance)


def ellipse_tool_vertices(
    tool: ConstructionEllipse, distance: float
) -> tuple[list[tuple[float, float]], bool]:
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
            vertices, tolerance = circle_vertices(edge, distance)
            error = max(error, tolerance)
        elif edge.dxftype() == "LINE":
            vertices = [edge.dxf.start, edge.dxf.end]
        else:
            raise TypeError("Unsupported polyline edge")
        if len(vertices) < 2:  # noqa: PLR2004 - an edge needs two endpoints
            raise ValueError("Degenerate polyline edge")
        # A negative bulge produces a reversed CCW ARC. Match the source order.
        if points[-1].distance(vertices[-1]) < points[-1].distance(vertices[0]):
            vertices.reverse()
        if not points[-1].isclose(vertices[0], rel_tol=0, abs_tol=1e-7):
            raise ValueError("Disconnected polyline edges")
        points.extend(vertices[1:])
        if len(points) > MAX_VERTICES:
            raise ValueError("Curve vertex budget exceeded")
    return [(v.x, v.y) for v in points], error
