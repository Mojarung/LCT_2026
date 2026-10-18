"""Ограда из штрихов закрывается перемычками (application/fences.py).

Харьковская: 4 362 куска ограды, 96 % короче 3 м, у четверти зазор 0,5 м. Плитка от подписи
«А» протекала сквозь такие зазоры за ограду детской площадки у дома 1А.
"""

from __future__ import annotations

import shapely
import shapely.ops
from shapely.geometry import LineString, Point

from green.application.fences import bridge_fence_gaps
from green.domain.objects import Feature, ObjectClass, SourceRef


def _fence(i: int, coords: list[tuple[float, float]]) -> Feature:
    return Feature(
        SourceRef("12345678", "00000000", f"F{i}"),
        "ТОПО_Ограды",
        LineString(coords),
        object_class=ObjectClass.FENCE,
    )


def _dashed(
    ring: list[tuple[float, float]], dash: float, gap: float, skip: tuple[float, float] = (-1, -1)
) -> list[Feature]:
    """Ограда по контуру штрихами dash через зазор gap; skip - проём (от, до) по длине."""
    line = LineString(ring)
    pieces = []
    position = 0.0
    while position < line.length - 1e-9:
        end = min(position + dash, line.length)
        if not (skip[0] <= position and end <= skip[1]):
            piece = shapely.ops.substring(line, position, end)
            pieces.append(_fence(len(pieces), list(piece.coords)))
        position = end + gap
    return pieces


SQUARE = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0), (0.0, 0.0)]


def _open_ends(features: tuple[Feature, ...]) -> int:
    lines = shapely.union_all([f.geometry for f in features if f.object_class is ObjectClass.FENCE])
    merged = shapely.line_merge(lines)
    return sum(
        0 if part.is_ring else 2
        for part in shapely.get_parts(merged)
        if part.geom_type == "LineString"
    )


def test_dashed_fence_becomes_closed() -> None:
    strokes = _dashed(SQUARE, 1.5, 0.5)

    features, bridged = bridge_fence_gaps(strokes)

    assert bridged > 30
    assert _open_ends(features) == 0
    assert (
        len(
            shapely.get_parts(
                shapely.polygonize([shapely.union_all([f.geometry for f in features])])
            )
        )
        == 1
    )


def test_gate_wider_than_a_metre_stays_open() -> None:
    # Проём 2 м на южной стороне (с 9 по 11 м контура).
    strokes = _dashed(SQUARE, 1.0, 0.5, skip=(8.9, 11.6))

    features, _ = bridge_fence_gaps(strokes)

    assert _open_ends(features) == 2
    gate = Point(10, 0)
    assert all(f.geometry.distance(gate) > 0.4 for f in features)


def test_sharp_corner_closes_only_when_the_gap_is_small() -> None:
    near = [_fence(1, [(0, 5), (0, 0.3)]), _fence(2, [(0.3, 0), (5, 0)])]
    far = [_fence(3, [(10, 5), (10, 0.5)]), _fence(4, [(10.5, 0), (15, 0)])]

    _, bridged_near = bridge_fence_gaps(near)
    _, bridged_far = bridge_fence_gaps(far)

    assert bridged_near == 1
    assert bridged_far == 0
