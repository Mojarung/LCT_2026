"""Bounded native HATCH curves and even/odd nesting of every rendered loop.

Заливка штриховки - как её рисует CAD (решение пользователя 25.09.2026): точка залита, если луч
из неё пересекает контуры нечётное число раз. Контуры, которые не пересекаются, вкладываются
друг в друга (острова); пересекающиеся и самопересекающиеся контуры заливаются тем же правилом
чёт-нечет точно, без погрешности. Разрыв контура CAD замыкает хордой: так же и здесь, а длина
разрыва уходит в погрешность - неизвестный кусок контура не выдаётся за точный. Каждая такая
починка возвращается списком, чтобы учёт исходов её показал.
"""

from __future__ import annotations

from collections import defaultdict
from functools import reduce
from typing import TYPE_CHECKING

import numpy as np
import shapely
from ezdxf.entities import LWPolyline
from ezdxf.entities.boundary_paths import ArcEdge, EdgePath, EllipseEdge, LineEdge, PolylinePath
from ezdxf.math import Vec2
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon

from green.infrastructure.cad.curve_paths import (
    MAX_VERTICES,
    arc_tool_vertices,
    ellipse_tool_vertices,
    polyline_vertices,
)

if TYPE_CHECKING:
    from ezdxf.entities.boundary_paths import AbstractBoundaryPath, AbstractEdge
    from ezdxf.entities.polygon import DXFPolygon
    from shapely.geometry.base import BaseGeometry

# Починки контура, которые попадают в учёт исходов ридера.
EVEN_ODD = "hatch-even-odd"
GAP_CLOSED = "hatch-gap-closed"


class HatchGeometryError(ValueError):
    """A specific unsupported or ambiguous area, recorded in import diagnostics."""


def hatch_geometry(
    entity: DXFPolygon, distance: float
) -> tuple[Polygon | MultiPolygon, float, tuple[str, ...]]:
    """Область штриховки, наибольшая погрешность и починки контура (пусто - контур точен)."""
    _require_supported(entity)
    rings, errors, repairs = _rings(entity, distance)
    if all(ring.is_valid and ring.area > 0 for ring in rings):
        try:
            return _nested_area(rings), max(errors), tuple(sorted(repairs))
        except HatchGeometryError:
            pass  # контуры пересекаются: та же заливка чёт-нечет, но через узлы пересечений
    repairs.add(EVEN_ODD)
    return _even_odd_area(rings), max(errors), tuple(sorted(repairs))


def _require_supported(entity: DXFPolygon) -> None:
    if entity.dxftype() == "MPOLYGON":
        if Vec2(entity.dxf.offset_vector).magnitude:
            raise HatchGeometryError("mpolygon-offset-not-supported")
        if entity.dxf.degenerated_loops:
            raise HatchGeometryError("mpolygon-degenerate-loops-not-supported")
    if entity.dxf.hatch_style not in {0, 1, 2}:
        raise HatchGeometryError("hatch-style-not-supported")


def _rings(entity: DXFPolygon, distance: float) -> tuple[list[Polygon], list[float], set[str]]:
    """Контуры, которые CAD заливает при стиле штриховки, в координатах чертежа."""
    ocs, elevation = entity.ocs(), entity.dxf.elevation.z
    rings, errors, repairs = [], [], set()
    vertices_used = 0
    for path in entity.paths.rendering_paths(entity.dxf.hatch_style):
        points, error, closed_gap = _ring(path, distance)
        if closed_gap:
            repairs.add(GAP_CLOSED)
        vertices_used += len(points)
        if vertices_used > MAX_VERTICES:
            raise HatchGeometryError("hatch-vertex-budget-exceeded")
        vertices = [ocs.to_wcs((x, y, elevation)) for x, y in points]
        polygon = Polygon([(v.x, v.y) for v in vertices])
        if not np.isfinite(shapely.get_coordinates(polygon)).all():
            raise HatchGeometryError("hatch-non-finite-coordinates")
        if polygon.is_empty:
            raise HatchGeometryError("hatch-invalid-ring")
        rings.append(polygon)
        errors.append(error)
    if not rings:
        raise HatchGeometryError("hatch-no-rendered-boundary")
    return rings, errors, repairs


def _ring(
    path: AbstractBoundaryPath, distance: float
) -> tuple[list[tuple[float, float]], float, bool]:
    """Точки замкнутого контура, погрешность и признак «разрыв замкнут хордой»."""
    closed_gap = False
    if isinstance(path, PolylinePath):
        line = LWPolyline.new(dxfattribs={"flags": int(path.is_closed)})
        line.set_points(path.vertices, format="xyb")
        points, error = polyline_vertices(line, distance)
    elif isinstance(path, EdgePath):
        points, error, closed_gap = _edge_ring(path, distance)
    else:
        raise HatchGeometryError("hatch-boundary-type-not-supported")
    if len(points) < 3:  # noqa: PLR2004 - minimum polygon vertex count
        raise HatchGeometryError("hatch-degenerate-ring")
    gap = Vec2(points[0]).distance(Vec2(points[-1]))
    # A closed polyline includes its closing edge by definition. A real gap is closed by a
    # chord, as CAD fills it; the chord length is the bound of the unknown boundary piece.
    if gap > distance * 1e-6:
        points.append(points[0])
        closed_gap = True
    else:
        points[-1] = points[0]
    return points, error + gap, closed_gap


def _edge_ring(path: EdgePath, distance: float) -> tuple[list[tuple[float, float]], float, bool]:
    points = []
    error, joint_error = 0.0, 0.0
    for edge in path.edges:
        vertices, tolerance = _edge_vertices(edge, distance)
        if len(vertices) < 2:  # noqa: PLR2004 - minimum edge vertex count
            raise HatchGeometryError("hatch-degenerate-edge")
        if points:
            gap = Vec2(points[-1]).distance(vertices[0])
            joint_error = max(joint_error, gap)
            # Стык рёбер точнее допуска - одна вершина; разрыв - хорда между рёбрами.
            if gap <= distance * 1e-6:
                vertices = vertices[1:]
        points.extend((v.x, v.y) for v in vertices)
        error = max(error, tolerance)
        if len(points) > MAX_VERTICES:
            raise HatchGeometryError("hatch-vertex-budget-exceeded")
    return points, error + joint_error, joint_error > distance * 1e-6


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


def _even_odd_area(rings: list[Polygon]) -> Polygon | MultiPolygon:
    """Заливка по правилу чёт-нечет всех контуров сразу: make_valid(linework) даёт чёт-нечет
    одного контура точно (узлы в точках самопересечения), симметрическая разность складывает
    контуры по модулю два. Вершины контура не сдвигаются: погрешность не растёт."""
    parts = [_polygonal(shapely.make_valid(ring, method="linework")) for ring in rings]
    # Попарно: symmetric_difference_all в shapely 2.1 считает неверно (shapely#2027).
    area = _polygonal(reduce(shapely.symmetric_difference, parts))
    if area.is_empty or area.area == 0:
        raise HatchGeometryError("hatch-zero-area")
    return area


def _polygonal(geometry: BaseGeometry) -> Polygon | MultiPolygon:
    """Площадные части результата: линии и точки вырожденных кусков заливки не дают."""
    polygons = [
        part
        for part in shapely.get_parts(shapely.get_parts(geometry))
        if part.geom_type == "Polygon" and part.area > 0
    ]
    if not polygons:
        return Polygon()
    merged = shapely.union_all(polygons)
    return merged if isinstance(merged, (Polygon, MultiPolygon)) else Polygon()


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
