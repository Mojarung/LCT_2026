"""Experimental rational-spline flattening with exact control-hull decisions.

Not connected to the CAD reader. Fractions represent the input IEEE doubles exactly;
knot insertion and subdivision use rational arithmetic. Independent sampling checks
the implementation, while the geometric bound follows from the convex hull property.
"""
# ruff: noqa: INP001 -- standalone research module, not a package

from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter
from fractions import Fraction
from itertools import pairwise
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

Point = tuple[Fraction, Fraction]
Homogeneous = tuple[Fraction, Fraction, Fraction]
MAX_CONTROL_POINTS = 128
MAX_DEGREE = 10
MAX_DEPTH = 32


def flatten_spline(  # noqa: C901, PLR0913 -- bounded subdivision with explicit refusal paths
    control_points: Sequence[tuple[float, float]],
    knots: Sequence[float],
    degree: int,
    weights: Sequence[float] = (),
    *,
    distance: float = 0.1,
    max_vertices: int = 4096,
) -> list[tuple[float, float]]:
    """Bound XY Hausdorff error by distance for continuous, clamped, positive-weight NURBS.

    Unsupported or excessive work raises ValueError; no partial result is returned.
    This bounds mathematical geometry from the parsed doubles, not survey accuracy.
    """
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("finite-positive-tolerance-required")
    if max_vertices < 2:  # noqa: PLR2004 -- a chord needs two endpoints
        raise ValueError("spline-vertex-budget")
    segments = _beziers(control_points, knots, degree, weights)
    half_squared = (Fraction(distance) / 2) ** 2
    result: list[tuple[float, float]] = []
    stack = [(segment, 0) for segment in reversed(segments)]
    while stack:
        control, depth = stack.pop()
        xy = [_project(p) for p in control]
        if all(_distance_squared(p, xy[0], xy[-1]) <= half_squared for p in xy):
            rounded = [(float(x), float(y)) for x, y in (xy[0], xy[-1])]
            for exact, value in zip((xy[0], xy[-1]), rounded, strict=True):
                error = sum((a - Fraction(b)) ** 2 for a, b in zip(exact, value, strict=True))
                if error > half_squared:
                    raise ValueError("coordinate-rounding-exceeds-budget")
            if not result:
                result.append(rounded[0])
            if result[-1] != rounded[0]:
                raise ValueError("disconnected-bezier-segments")
            result.append(rounded[1])
            if len(result) > max_vertices:
                raise ValueError("spline-vertex-budget")
        else:
            if depth >= MAX_DEPTH or len(result) + len(stack) + 2 >= max_vertices:
                raise ValueError("spline-subdivision-budget")
            left, right = _split(control)
            stack.extend(((right, depth + 1), (left, depth + 1)))
    return result


def _beziers(
    control_points: Sequence[tuple[float, float]],
    knots: Sequence[float],
    degree: int,
    weights: Sequence[float],
) -> list[list[Homogeneous]]:
    if not 1 <= degree <= MAX_DEGREE or not degree < len(control_points) <= MAX_CONTROL_POINTS:
        raise ValueError("spline-control-budget-or-degree")
    if len(knots) != len(control_points) + degree + 1:
        raise ValueError("invalid-knot-count")
    if weights and len(weights) != len(control_points):
        raise ValueError("invalid-weight-count")
    u = [Fraction(float(v)) for v in knots]
    w = [Fraction(float(v)) for v in weights] if weights else [Fraction(1)] * len(control_points)
    if any(value <= 0 for value in w):
        raise ValueError("positive-weights-required")
    if any(b < a for a, b in pairwise(u)) or u[0] >= u[-1]:
        raise ValueError("invalid-knot-order")
    counts = Counter(u)
    if counts[u[0]] != degree + 1 or counts[u[-1]] != degree + 1:
        raise ValueError("clamped-spline-required")
    interior = [(value, count) for value, count in counts.items() if u[0] < value < u[-1]]
    if any(count > degree for _, count in interior):
        raise ValueError("discontinuous-spline-not-supported")
    points = [
        (Fraction(float(x)) * weight, Fraction(float(y)) * weight, weight)
        for (x, y), weight in zip(control_points, w, strict=True)
    ]
    # Boehm insertion: each internal knot reaches degree multiplicity, producing
    # exact rational Bezier segments. Distinct knots are never tolerance-merged.
    for value, count in interior:
        for _ in range(degree - count):
            u, points = _insert(u, points, degree, value)
    return [points[i : i + degree + 1] for i in range(0, len(points) - 1, degree)]


def _project(point: Homogeneous) -> Point:
    return point[0] / point[2], point[1] / point[2]


def _mix(a: Homogeneous, b: Homogeneous, alpha: Fraction) -> Homogeneous:
    x, y, weight = ((1 - alpha) * x + alpha * y for x, y in zip(a, b, strict=True))
    return x, y, weight


def _insert(
    knots: list[Fraction], points: list[Homogeneous], degree: int, value: Fraction
) -> tuple[list[Fraction], list[Homogeneous]]:
    span = bisect_right(knots, value) - 1
    multiplicity = knots.count(value)
    changed = points[: span - degree + 1]
    for i in range(span - degree + 1, span - multiplicity + 1):
        alpha = (value - knots[i]) / (knots[i + degree] - knots[i])
        changed.append(_mix(points[i - 1], points[i], alpha))
    changed.extend(points[span - multiplicity :])
    return [*knots[: span + 1], value, *knots[span + 1 :]], changed


def _split(points: list[Homogeneous]) -> tuple[list[Homogeneous], list[Homogeneous]]:
    level = points
    left, right = [level[0]], [level[-1]]
    while len(level) > 1:
        level = [_mix(a, b, Fraction(1, 2)) for a, b in pairwise(level)]
        left.append(level[0])
        right.append(level[-1])
    return left, right[::-1]


def _distance_squared(point: Point, start: Point, end: Point) -> Fraction:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if not length_squared:
        return (point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2
    t = max(
        Fraction(0),
        min(
            Fraction(1), ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
        ),
    )
    return (point[0] - start[0] - t * dx) ** 2 + (point[1] - start[1] - t * dy) ** 2
