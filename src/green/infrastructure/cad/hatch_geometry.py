"""Bounded native HATCH curves and even/odd nesting of every rendered loop."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np
import shapely
from ezdxf.entities import LWPolyline
from ezdxf.entities.boundary_paths import ArcEdge, EdgePath, EllipseEdge, LineEdge, PolylinePath
from ezdxf.math import Vec2, Vec3
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon

from green.infrastructure.cad.curve_paths import (
    MAX_VERTICES,
    arc_tool_vertices,
    ellipse_tool_vertices,
    polyline_vertices,
)
from green.infrastructure.cad.polygon_repair import repair_roundoff_self_intersection

if TYPE_CHECKING:
    from ezdxf.entities.boundary_paths import AbstractBoundaryPath, AbstractEdge
    from ezdxf.entities.polygon import DXFPolygon


class HatchGeometryError(ValueError):
    """A specific unsupported or ambiguous area, recorded in import diagnostics."""


_MAX_CLOSURE_FRACTION = 0.02


def hatch_geometry(
    entity: DXFPolygon, distance: float, *, max_closure: float
) -> tuple[Polygon | MultiPolygon, float]:
    if entity.dxftype() == "MPOLYGON":
        if Vec2(entity.dxf.offset_vector).magnitude:
            raise HatchGeometryError("mpolygon-offset-not-supported")
        if entity.dxf.degenerated_loops:
            raise HatchGeometryError("mpolygon-degenerate-loops-not-supported")
    style = entity.dxf.hatch_style
    if style not in {0, 1, 2}:
        raise HatchGeometryError("hatch-style-not-supported")
    ocs, elevation = entity.ocs(), entity.dxf.elevation.z
    rings, errors = [], []
    vertices_used = 0
    for path in entity.paths.rendering_paths(style):
        points, error = _ring(path, distance, max_closure)
        vertices_used += len(points)
        if vertices_used > MAX_VERTICES:
            raise HatchGeometryError("hatch-vertex-budget-exceeded")
        vertices = [ocs.to_wcs((x, y, elevation)) for x, y in points]
        rings.append(_checked_ring(vertices))
        errors.append(error)
    if not rings:
        raise HatchGeometryError("hatch-no-rendered-boundary")
    return _compose_rings(rings, errors)


def _checked_ring(vertices: list[Vec3]) -> Polygon:
    polygon = Polygon([(v.x, v.y) for v in vertices])
    if not np.isfinite(shapely.get_coordinates(polygon)).all():
        raise HatchGeometryError("hatch-non-finite-coordinates")
    if polygon.is_empty or polygon.area == 0:
        raise HatchGeometryError("hatch-invalid-ring")
    if not polygon.is_valid:
        repaired = repair_roundoff_self_intersection(polygon)
        if repaired is None:
            raise HatchGeometryError("hatch-invalid-ring")
        polygon = repaired
    return polygon


def _compose_rings(
    rings: list[Polygon], errors: list[float]
) -> tuple[Polygon | MultiPolygon, float]:
    if len(rings) == 1:
        return rings[0], errors[0]
    if any(ring.interiors for ring in rings):
        raise HatchGeometryError("hatch-repaired-ring-nesting-unsupported")
    return _nested_area(rings), max(errors)


def _ring(
    path: AbstractBoundaryPath, distance: float, max_closure: float
) -> tuple[list[tuple[float, float]], float]:
    if isinstance(path, PolylinePath):
        line = LWPolyline.new(dxfattribs={"flags": int(path.is_closed)})
        line.set_points(path.vertices, format="xyb")
        points, error = polyline_vertices(line, distance)
    elif isinstance(path, EdgePath):
        points, error = _edge_ring(path, distance)
    else:
        raise HatchGeometryError("hatch-boundary-type-not-supported")
    if len(points) < 3:  # noqa: PLR2004 - minimum polygon vertex count
        raise HatchGeometryError("hatch-degenerate-ring")
    gap = Vec2(points[0]).distance(Vec2(points[-1]))
    # Permit a seam shorter than 2% of the curve bound and an absolute cap.
    # Moving the final point to the first changes the boundary by at most gap;
    # that displacement is included in the returned error bound.
    if gap > min(distance * _MAX_CLOSURE_FRACTION, max_closure):
        raise HatchGeometryError("hatch-open-boundary")
    points[-1] = points[0]
    return points, error + gap


def _edge_ring(path: EdgePath, distance: float) -> tuple[list[tuple[float, float]], float]:
    points = []
    error, joint_error = 0.0, 0.0
    for edge in path.edges:
        vertices, tolerance = _edge_vertices(edge, distance)
        if len(vertices) < 2:  # noqa: PLR2004 - minimum edge vertex count
            raise HatchGeometryError("hatch-degenerate-edge")
        if points:
            gap = Vec2(points[-1]).distance(vertices[0])
            if gap > distance * 1e-6:
                raise HatchGeometryError("hatch-disconnected-edges")
            joint_error = max(joint_error, gap)
            vertices = vertices[1:]
        points.extend((v.x, v.y) for v in vertices)
        error = max(error, tolerance)
        if len(points) > MAX_VERTICES:
            raise HatchGeometryError("hatch-vertex-budget-exceeded")
    return points, error + joint_error


def _edge_vertices(edge: AbstractEdge, distance: float) -> tuple[list[Vec2], float]:
    if isinstance(edge, LineEdge):
        return [edge.start, edge.end], 0.0
    if isinstance(edge, ArcEdge):
        vertices, tolerance = arc_tool_vertices(edge.construction_tool(), distance)
    elif isinstance(edge, EllipseEdge):
        sampled, _ = ellipse_tool_vertices(edge.construction_tool(), distance)
        vertices, tolerance = [Vec2(v) for v in sampled], distance
    else:
        raise HatchGeometryError("hatch-curve-bound-not-supported")
    if not edge.ccw:
        vertices.reverse()
    return vertices, tolerance


def _nested_area(rings: list[Polygon]) -> Polygon | MultiPolygon:
    # Crossing/touching rings need a different topology policy; reject instead
    # of silently repairing a material region. Use geometry, not bounding boxes.
    boundaries = [ring.boundary for ring in rings]
    pairs = STRtree(boundaries).query(boundaries, predicate="intersects")
    if (pairs[0] != pairs[1]).any():
        raise HatchGeometryError("hatch-intersecting-boundaries")
    within = STRtree(rings).query(rings, predicate="within")
    containers = defaultdict(list)
    for child, parent in zip(*within, strict=True):
        if child != parent:
            containers[int(child)].append(int(parent))
    holes = defaultdict(list)
    for child, parents in containers.items():
        if len(parents) % 2:
            parent = min(parents, key=lambda i: rings[i].area)
            holes[parent].append(rings[child].exterior.coords)
    polygons = [
        Polygon(ring.exterior.coords, holes[i])
        for i, ring in enumerate(rings)
        if len(containers[i]) % 2 == 0
    ]
    area = MultiPolygon(polygons) if len(polygons) > 1 else polygons[0]
    if not area.is_valid:
        raise HatchGeometryError("hatch-invalid-nesting")
    return area
