"""Curve sampling with an explicit distance bound in drawing coordinates."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from ezdxf.entities import Arc, Circle, LWPolyline
from ezdxf.math import arc_segment_count

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ezdxf.entities import Ellipse, Polyline, Spline
    from ezdxf.math import ConstructionArc, ConstructionEllipse, Vec2, Vec3
    from numpy.typing import NDArray

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


# Стрелка дуги (отклонение от хорды) меньше этого - прямой отрезок, в единицах чертежа. Выпуклость
# 1e-13 у борта Олимпийской деревни ezdxf превращает в дугу радиусом 10^14, её концы расходятся
# с вершинами на точности float. Микрометр на порядки меньше любого допуска чтения.
_STRAIGHT_SAGITTA = 1e-6


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
    for edge in _straightened(entity).virtual_entities():
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


def _straightened(entity: LWPolyline | Polyline) -> LWPolyline | Polyline:
    """Копия без выпуклостей, чья дуга неотличима от хорды; исходник не меняется."""
    if isinstance(entity, LWPolyline):
        rows = list(entity.get_points("xyseb"))
        count = len(rows)
        noise = [
            i
            for i, (x, y, _, _, bulge) in enumerate(rows)
            if bulge and _sagitta(bulge, (x, y), rows[(i + 1) % count][:2]) < _STRAIGHT_SAGITTA
        ]
        if not noise:
            return entity
        copy = entity.copy()
        copy.set_points([(*row[:4], 0.0 if i in noise else row[4]) for i, row in enumerate(rows)])
        return copy
    vertices = list(entity.vertices)
    count = len(vertices)
    noise = [
        i
        for i, vertex in enumerate(vertices)
        if vertex.dxf.bulge
        and _sagitta(vertex.dxf.bulge, vertex.dxf.location, vertices[(i + 1) % count].dxf.location)
        < _STRAIGHT_SAGITTA
    ]
    if not noise:
        return entity
    copy = entity.copy()
    for i in noise:
        copy.vertices[i].dxf.bulge = 0.0
    return copy


def _sagitta(bulge: float, start: Sequence[float], end: Sequence[float]) -> float:
    """Стрелка дуги: выпуклость - тангенс четверти угла, стрелка = выпуклость * хорда / 2."""
    return abs(bulge) * math.dist((start[0], start[1]), (end[0], end[1])) / 2


# Предел деления одной кривой Безье: 2**24 кусков дальше любого бюджета вершин.
_MAX_SPLIT_DEPTH = 24


def spline_vertices(entity: Spline, distance: float) -> tuple[list[tuple[float, float]], float]:
    """Нерациональный сплайн - точная цепочка кривых Безье; каждая делится пополам (де Кастельжо),
    пока её внутренние контрольные точки не окажутся ближе `distance` к хорде.

    Кривая лежит в выпуклой оболочке своих контрольных точек, расстояние до хорды выпукло,
    поэтому оценка строгая, а не проверка в середине отрезка. Проекция на план - аффинное
    отображение, контрольные точки проецируются вместе с кривой. Рациональный или незажатый
    сплайн так не раскладывается, а сплайн только из точек прохождения каждая CAD-программа
    строит своей интерполяцией: ValueError, вызывающий оставляет пробел.
    """
    if not entity.control_point_count():
        raise ValueError("Fit-point spline: the curve depends on the CAD interpolation")
    try:
        segments = list(entity.construction_tool().bezier_decomposition())
    except TypeError as error:
        raise ValueError(str(error)) from error
    if not segments:
        raise ValueError("Empty spline")
    points = [(segments[0][0].x, segments[0][0].y)]
    bound = 0.0
    for control in segments:
        pending = [(np.array([(v.x, v.y) for v in control], dtype=np.float64), 0)]
        while pending:
            part, depth = pending.pop()
            deviation = _control_deviation(part)
            if deviation <= distance or depth >= _MAX_SPLIT_DEPTH:
                points.append((float(part[-1, 0]), float(part[-1, 1])))
                bound = max(bound, deviation)
                if len(points) > MAX_VERTICES:
                    raise ValueError("Curve vertex budget exceeded")
                continue
            left, right = _split_half(part)
            pending.extend(((right, depth + 1), (left, depth + 1)))
    return points, max(bound, distance)


def _control_deviation(control: NDArray[np.float64]) -> float:
    """Наибольшее расстояние внутренних контрольных точек до хорды (отрезка)."""
    start, end = control[0], control[-1]
    inner = control[1:-1]
    if not len(inner):
        return 0.0
    chord = end - start
    length = float(chord @ chord)
    if length == 0:
        return float(np.hypot(*(inner - start).T).max())
    t = np.clip(((inner - start) @ chord) / length, 0.0, 1.0)
    return float(np.hypot(*(inner - (start + t[:, None] * chord)).T).max())


def _split_half(control: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    left, right = [control[0]], [control[-1]]
    level = control
    while len(level) > 1:
        level = (level[:-1] + level[1:]) / 2
        left.append(level[0])
        right.append(level[-1])
    return np.array(left), np.array(right[::-1])


# Флаги 2D-полилинии и её вершин (DXF): сглажена сплайном; вершина сглаживания; вершина рамки.
_SPLINE_FIT = 4
_FIT_VERTEX = 8
_FRAME_VERTEX = 16


def fitted_vertices(entity: Polyline) -> list[tuple[float, float]] | None:
    """Вершины, которые CAD рисует у 2D-полилинии, сглаженной сплайном: вершины сглаживания,
    без рамки. ezdxf строит путь по всем вершинам подряд - зигзаг между кривой и рамкой.
    None - полилиния не сглажена сплайном или у вершин сглаживания есть дуги.
    """
    if not (entity.is_2d_polyline and entity.dxf.flags & _SPLINE_FIT):
        return None
    shown = [v for v in entity.vertices if not v.dxf.flags & _FRAME_VERTEX]
    if not shown or any(v.dxf.get("bulge", 0.0) for v in shown):
        return None
    ocs = entity.ocs()
    elevation = entity.dxf.elevation.z
    return [
        (point.x, point.y)
        for point in (ocs.to_wcs((v.dxf.location.x, v.dxf.location.y, elevation)) for v in shown)
    ]
