"""Bounded native HATCH curves and even/odd nesting of every rendered loop."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import TYPE_CHECKING

import numpy as np
import shapely
from ezdxf.entities import LWPolyline
from ezdxf.entities.boundary_paths import ArcEdge, EdgePath, EllipseEdge, LineEdge, PolylinePath
from ezdxf.entities.polygon import DXFPolygon
from ezdxf.math import Vec2, Vec3
from shapely import STRtree
from shapely.affinity import affine_transform
from shapely.errors import GEOSException
from shapely.geometry import LineString, MultiPolygon, Polygon

from green.infrastructure.cad.curve_paths import (
    MAX_VERTICES,
    arc_tool_vertices,
    ellipse_tool_vertices,
    polyline_vertices,
)
from green.infrastructure.cad.polygon_repair import repair_roundoff_self_intersection

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ezdxf.entities import Polyline
    from ezdxf.entities.boundary_paths import AbstractBoundaryPath, AbstractEdge
    from ezdxf.math import Matrix44


class HatchGeometryError(ValueError):
    """A specific unsupported or ambiguous area, recorded in import diagnostics."""


_MAX_CLOSURE_FRACTION = 0.02
_MAX_MATCH_AREA_FRACTION = 0.02
_MAX_MATCH_WIDTH_FRACTION = 0.02
_MAX_ROUNDOFF_OVERLAP_FRACTION = 1e-12
_MAX_ASSOCIATED_PATH_SIZE_FRACTION = 0.05
_MAX_TINY_LOBE_AREA_FRACTION = 0.001
_MAX_TINY_LOBE_DIAMETERS_PER_CLOSURE = 10
_MAX_TINY_LOBE_BOUNDARY_SHIFT = 1e-9
_LOCAL_TRANSFORM_ROUNDOFF_ULPS = 64


def associated_polyline_error(  # noqa: PLR0913 - source and matched boundary need their bounds
    polyline: Polyline,
    points: list[tuple[float, float]],
    source_error: float,
    sibling_hatches: Sequence[DXFPolygon],
    distance: float,
    *,
    max_closure: float,
    max_shift: float,
) -> float | None:
    """Bound a fitted POLYLINE only against its explicit, matching HATCH source path."""
    source = polyline.origin_of_copy or polyline
    handle = source.dxf.get("handle")
    if not handle or not polyline.is_closed or len(points) < 3:  # noqa: PLR2004
        return None
    rendered = LineString(points)
    matches = []
    for hatch in sibling_hatches:
        original = hatch.origin_of_copy or hatch
        if (
            not isinstance(original, DXFPolygon)
            or source.dxf.get("owner") != original.dxf.get("owner")
            or polyline.dxf.get("layer", "0") != hatch.dxf.get("layer", "0")
            or len(original.paths.paths) != len(hatch.paths.paths)
        ):
            continue
        for declared, path in zip(original.paths.paths, hatch.paths.paths, strict=True):
            if declared.source_boundary_objects != [handle]:
                continue
            try:
                polygon, path_error, _ = _path_polygon(hatch, path, distance, max_closure)
                ring = _checked_ring(polygon)
                shift = rendered.hausdorff_distance(ring.boundary)
            except HatchGeometryError, GEOSException, ValueError:
                continue
            tolerance = min(
                max_shift,
                source_error + path_error,
                _MAX_ASSOCIATED_PATH_SIZE_FRACTION * math.sqrt(ring.area),
            )
            if math.isfinite(shift) and shift <= tolerance:
                matches.append(max(source_error, path_error + shift))
    return matches[0] if len(matches) == 1 else None


def linear_hatch_from_local_source(  # noqa: C901, PLR0911 - each failed check rejects fallback
    entity: DXFPolygon,
    matrix: Matrix44,
    distance: float,
    *,
    max_closure: float,
) -> tuple[Polygon | MultiPolygon, float] | None:
    """Compose straight rings before a block transform when WCS rounding breaks adjacency."""
    source = entity.origin_of_copy
    if (
        not isinstance(source, DXFPolygon)
        or source.dxf.elevation.z != 0
        or source.dxf.hatch_style != entity.dxf.hatch_style
    ):
        return None
    try:
        local, local_error = hatch_geometry(source, distance, max_closure=max_closure)
        local_extent = max(abs(value) for value in local.bounds)
        local_roundoff = _LOCAL_TRANSFORM_ROUNDOFF_ULPS * math.ulp(local_extent)
        if local_error > local_roundoff:
            return None
        local_paths = list(source.paths.rendering_paths(source.dxf.hatch_style))
        virtual_paths = list(entity.paths.rendering_paths(entity.dxf.hatch_style))
        if len(local_paths) != len(virtual_paths) or not local_paths:
            return None
        if any(not _straight_path(path) for path in local_paths):
            return None
        x_axis = matrix.transform_direction(Vec3(1, 0, 0))
        y_axis = matrix.transform_direction(Vec3(0, 1, 0))
        origin = matrix.transform(Vec3(0, 0, 0))
        coefficients = [x_axis.x, y_axis.x, x_axis.y, y_axis.y, origin.x, origin.y]
        transformed = affine_transform(local, coefficients)
        if transformed.is_empty:
            return None
        extent = max(abs(value) for value in transformed.bounds)
        roundoff = _LOCAL_TRANSFORM_ROUNDOFF_ULPS * math.ulp(extent)
        transformed = _valid_transformed_area(transformed, roundoff)
        if transformed is None:
            return None
        for local_path, virtual_path in zip(local_paths, virtual_paths, strict=True):
            local_ring, local_bound, _ = _path_polygon(source, local_path, distance, max_closure)
            virtual_ring, virtual_bound, _ = _path_polygon(
                entity, virtual_path, distance, max_closure
            )
            if local_bound > local_roundoff or virtual_bound != 0:
                return None
            expected = affine_transform(_checked_ring(local_ring), coefficients)
            observed = _checked_ring(virtual_ring)
            if not (
                expected.is_valid
                and expected.buffer(roundoff).covers(observed)
                and observed.buffer(roundoff).covers(expected)
            ):
                return None
        scale = max(x_axis.magnitude, y_axis.magnitude)
        return transformed, roundoff + local_error * scale
    except HatchGeometryError, GEOSException, ValueError:
        return None


def _straight_path(path: AbstractBoundaryPath) -> bool:
    if isinstance(path, PolylinePath):
        return all(bulge == 0 for _, _, bulge in path.vertices)
    return isinstance(path, EdgePath) and all(isinstance(edge, LineEdge) for edge in path.edges)


def _valid_transformed_area(
    area: Polygon | MultiPolygon, roundoff: float
) -> Polygon | MultiPolygon | None:
    if area.is_valid:
        return area
    repaired = shapely.make_valid(area)
    polygons = [
        part for part in shapely.get_parts(repaired) if isinstance(part, Polygon | MultiPolygon)
    ]
    if not polygons:
        return None
    polygonal = shapely.union_all(polygons)
    if not polygonal.is_valid or abs(polygonal.area - area.area) > roundoff * max(area.length, 1):
        return None
    return polygonal


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
    paths = list(entity.paths.rendering_paths(style))
    rings, errors = [], []
    vertices_used = 0
    for path in paths:
        polygon, error, count = _path_polygon(entity, path, distance, max_closure)
        vertices_used += count
        if vertices_used > MAX_VERTICES:
            raise HatchGeometryError("hatch-vertex-budget-exceeded")
        try:
            ring = _checked_ring(polygon)
        except HatchGeometryError:
            repaired = (
                _tiny_lobe_repair(polygon, max_closure * _MAX_TINY_LOBE_DIAMETERS_PER_CLOSURE)
                if len(paths) == 1
                else None
            )
            if repaired is None:
                raise
            area, ambiguity = repaired
            return area, error + ambiguity
        rings.append(ring)
        errors.append(error)
    if not rings:
        raise HatchGeometryError("hatch-no-rendered-boundary")
    return _compose_rings(rings, errors)


def _tiny_lobe_repair(  # noqa: PLR0911 - each failed geometric bound rejects the repair
    polygon: Polygon, max_diameter: float
) -> tuple[MultiPolygon, float] | None:
    """Keep every lobe only when all uncertain islands fit in a tiny error envelope."""
    if polygon.is_empty or not math.isfinite(polygon.area) or polygon.area <= 0:
        return None
    try:
        repaired = shapely.make_valid(polygon)
        if not isinstance(repaired, MultiPolygon) or not repaired.is_valid:
            return None
        parts = sorted(repaired.geoms, key=lambda part: part.area, reverse=True)
        main, satellites = parts[0], parts[1:]
        if not satellites or main.area <= 0:
            return None
        satellites_area = sum(part.area for part in satellites)
        if satellites_area > _MAX_TINY_LOBE_AREA_FRACTION * main.area:
            return None
        diameters = [
            math.hypot(part.bounds[2] - part.bounds[0], part.bounds[3] - part.bounds[1])
            for part in satellites
        ]
        ambiguity = max(diameters)
        if (
            not math.isfinite(ambiguity)
            or ambiguity > max_diameter
            or abs(polygon.area - main.area) > 4 * satellites_area + 1e-12
            or polygon.boundary.hausdorff_distance(repaired.boundary)
            > _MAX_TINY_LOBE_BOUNDARY_SHIFT
        ):
            return None
        return repaired, ambiguity  # noqa: TRY300 - validated result depends on the try block
    except GEOSException, ValueError:
        return None


def _checked_ring(polygon: Polygon) -> Polygon:
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


def hatch_outline(
    entity: DXFPolygon, distance: float, *, max_closure: float
) -> tuple[Polygon, float]:
    """Sample one HATCH ring before validating its possibly invalid topology."""
    paths = list(entity.paths.rendering_paths(entity.dxf.hatch_style))
    if len(paths) != 1:
        raise HatchGeometryError("hatch-region-match-needs-one-ring")
    polygon, error, _ = _path_polygon(entity, paths[0], distance, max_closure)
    return polygon, error


def match_region_outline(
    outline: Polygon,
    outline_error: float,
    candidates: list[tuple[Polygon, float]],
    *,
    max_shift: float,
) -> tuple[Polygon, float] | None:
    """Choose a unique REGION agreeing with a sampled HATCH within its error bound."""
    if outline.is_empty or not math.isfinite(outline.area) or outline.area <= 0:
        return None
    matches = []
    for region, region_error in candidates:
        if region.is_empty or not region.is_valid or region.area <= 0:
            continue
        tolerance = min(
            outline_error + region_error,
            max_shift,
            _MAX_MATCH_WIDTH_FRACTION * math.sqrt(region.area),
        )
        if not math.isfinite(tolerance) or tolerance < 0:
            continue
        try:
            boundary_shift = outline.boundary.hausdorff_distance(region.boundary)
        except GEOSException:
            continue
        if (
            boundary_shift <= tolerance
            and abs(outline.area - region.area) <= _MAX_MATCH_AREA_FRACTION * region.area
        ):
            matches.append((region, region_error + outline_error + boundary_shift))
    return matches[0] if len(matches) == 1 else None


def _path_polygon(
    entity: DXFPolygon, path: AbstractBoundaryPath, distance: float, max_closure: float
) -> tuple[Polygon, float, int]:
    points, error = _ring(path, distance, max_closure)
    if len(points) > MAX_VERTICES:
        raise HatchGeometryError("hatch-vertex-budget-exceeded")
    ocs, elevation = entity.ocs(), entity.dxf.elevation.z
    vertices = [ocs.to_wcs((x, y, elevation)) for x, y in points]
    polygon = Polygon([(v.x, v.y) for v in vertices])
    if not np.isfinite(shapely.get_coordinates(polygon)).all():
        raise HatchGeometryError("hatch-non-finite-coordinates")
    return polygon, error, len(points)


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
    # Adjacent filled rings may share an edge or vertex. Their interiors must
    # remain disjoint; overlapping or boundary-touching nested rings are ambiguous.
    boundaries = [ring.boundary for ring in rings]
    pairs = STRtree(boundaries).query(boundaries, predicate="intersects")
    for first, second in zip(*pairs, strict=True):
        if first >= second or rings[first].touches(rings[second]):
            continue
        overlap = rings[first].intersection(rings[second]).area
        if overlap > _MAX_ROUNDOFF_OVERLAP_FRACTION * min(rings[first].area, rings[second].area):
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
    area = shapely.union_all(polygons) if len(polygons) > 1 else polygons[0]
    if not area.is_valid:
        raise HatchGeometryError("hatch-invalid-nesting")
    expected = sum(polygon.area for polygon in polygons)
    if not math.isclose(area.area, expected, rel_tol=1e-10, abs_tol=1e-10):
        raise HatchGeometryError("hatch-intersecting-boundaries")
    return area
