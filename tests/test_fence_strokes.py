"""Ограда из штрихов закрывается перемычками (application/fences.py).

Харьковская: 4 362 куска ограды, 96 % короче 3 м, у четверти зазор 0,5 м. Плитка от подписи
«А» протекала сквозь такие зазоры за ограду детской площадки у дома 1А.
"""

from __future__ import annotations

from pathlib import Path

import shapely
import shapely.ops
from shapely.geometry import LineString, Point

from green.application import fences as fences_module
from green.application.fences import JOIN_M, _medial_axis, bridge_fence_gaps, fence_axes
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


def test_double_line_fence_with_post_circles_becomes_one_axis() -> None:
    """Ограда на столбах в съёмке - две параллельные линии через 0,3 м и кружки столбов. В 3D
    она вставала двумя рядами решётки с кусками вразнобой (пользователь, 19.10.2026: «как
    будто человек раскидал объекты»). Ось - одна линия посередине, кружки не дают оград."""
    left = LineString([(0, 0.15), (30, 0.15)])
    right = LineString([(0, -0.15), (12, -0.15)])
    right2 = LineString([(12.4, -0.15), (30, -0.15)])  # разрыв штриха
    posts = [Point(x, 0).buffer(0.25).exterior for x in range(0, 31, 3)]
    axes = fence_axes([left, right, right2, *posts])
    assert len(axes) == 1
    axis = axes[0]
    assert axis.length > 28.5
    coords = shapely.get_coordinates(axis)
    assert abs(coords[:, 1]).max() < 0.1
    assert coords[:, 0].min() < 1
    assert coords[:, 0].max() > 29


def test_fence_corner_is_one_continuous_axis() -> None:
    """Угол ограды площадки: две стороны сходятся под прямым углом с зазором - ось одна,
    с углом, без разрыва (пользователь: «должен нормально стыковаться забор»)."""
    a = LineString([(0, 0), (10, 0)])
    b = LineString([(10.4, 0.4), (10.4, 10)])
    axes = fence_axes([a, b])
    assert len(axes) == 1
    assert axes[0].distance(Point(10.2, 0.2)) < 0.3
    assert axes[0].length > 18


def test_separate_fences_stay_separate() -> None:
    axes = fence_axes([LineString([(0, 0), (10, 0)]), LineString([(0, 5), (10, 5)])])
    assert len(axes) == 2


def test_fence_axis_gaps_up_to_join_m_are_closed() -> None:
    """Ось, разошедшаяся у развилки полосы, сшивается; проход 3 м остаётся."""
    a = LineString([(0, 0), (10, 0)])
    b = LineString([(10 + JOIN_M - 0.1, 0), (20, 0)])
    far = LineString([(23, 0), (30, 0)])  # проход 3 м
    axes = fence_axes([a, b, far])
    assert len(axes) == 2
    assert max(axis.length for axis in axes) > 19


def test_gate_a_metre_wide_stays_open() -> None:
    """Калитка площадки у дома 1А на Харьковской - разрыв ограды 1,37 м под дорожкой, на
    улице такие разрывы от 1,02 м, и все - проходы. Сшивка до 1,6 м закрывала их решёткой."""
    a = LineString([(0, 0), (10, 0)])
    b = LineString([(11.02, 0), (20, 0)])
    assert len(fence_axes([a, b])) == 2


def test_fence_band_that_broke_voronoi_still_gets_an_axis() -> None:
    """Старый Гай, 19.10.2026: полоса ограды с повторами точек контура в координатах около
    20 850 м - диаграмма Вороного GEOS падала («point array must contain 0 or >1 elements»),
    и с ней весь прогон улицы."""
    data = Path(__file__).parent / "data" / "fence_band_voronoi_failure.wkt"
    band = shapely.from_wkt(data.read_text(encoding="utf-8"))
    axes = _medial_axis(band)
    assert axes
    assert sum(a.length for a in axes) > 0.3 * band.length
    assert all(band.buffer(0.05).contains(a) for a in axes)


def test_geos_failure_on_one_band_keeps_its_strokes(monkeypatch) -> None:  # noqa: ANN001
    """Сбой GEOS на одной полосе не роняет прогон: её штрихи идут в 3D как есть."""

    def broken(_polygon: object) -> list:
        raise shapely.errors.GEOSException("boom")

    monkeypatch.setattr(fences_module, "_medial_axis", broken)
    axes = fence_axes([LineString([(0, 0), (10, 0)])])
    assert len(axes) == 1
    assert axes[0].length == 10
