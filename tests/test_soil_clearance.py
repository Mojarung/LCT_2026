"""Проверка «посадочное место целиком на грунте» считает точное расстояние только у близких точек.

Раньше расстояние от каждой точки до контура газона, покрытия и спорной зоны считалось
перебором всех вершин контура: на Кустанайской это 60 с на вариант плана. Теперь дальние
точки отсекает подготовленная проверка dwithin, точное расстояние остаётся у близких. Ответ
обязан совпасть с прямым сравнением `shapely.distance(points, geometry) >= r` бит в бит:
у точки ровно на r, внутри контура, у дырки и у пустого контура (NaN - не проходит).
"""

from __future__ import annotations

import numpy as np
import pytest
import shapely

from green.application.surfaces import distance_at_least


def _lawn() -> shapely.Polygon:
    """Газон с извилистым краем и двумя приямками внутри."""
    t = np.linspace(0, 2 * np.pi, 4000, endpoint=False)
    radius = 50 + 3 * np.sin(11 * t) + 0.4 * np.sin(97 * t)
    shell = np.column_stack((radius * np.cos(t), radius * np.sin(t)))
    holes = [shapely.box(-10, -5, -4, 5).exterior.coords, shapely.box(8, 8, 14, 20).exterior.coords]
    return shapely.Polygon(shell, holes=holes)


@pytest.mark.parametrize("radius", [0.3, 0.8, 1.6, 4.0])
@pytest.mark.parametrize("edge", [False, True])
def test_same_answer_as_plain_distance(radius: float, *, edge: bool) -> None:
    lawn = _lawn()
    geometry = lawn.boundary if edge else lawn
    rng = np.random.default_rng(7)
    points = shapely.points(rng.uniform(-60, 60, (6000, 2)))
    expected = shapely.distance(points, geometry) >= radius
    assert np.array_equal(distance_at_least(geometry, points, radius), expected)


def test_point_exactly_at_the_radius_passes() -> None:
    square = shapely.box(0, 0, 10, 10)
    points = shapely.points([(12.0, 5.0), (11.999, 5.0), (5.0, 5.0), (15.0, 15.0), (10.0, 12.0)])
    got = distance_at_least(square, points, 2.0)
    assert got.tolist() == [True, False, False, True, True]
    assert np.array_equal(got, shapely.distance(points, square) >= 2.0)


def test_empty_contour_lets_nothing_through() -> None:
    points = shapely.points([(0.0, 0.0), (100.0, 100.0)])
    for empty in (shapely.Polygon(), shapely.LineString(), shapely.GeometryCollection()):
        got = distance_at_least(empty, points, 1.0)
        assert not got.any()
        assert np.array_equal(got, shapely.distance(points, empty) >= 1.0)


def test_no_points() -> None:
    got = distance_at_least(shapely.box(0, 0, 1, 1), shapely.points(np.zeros((0, 2))), 1.0)
    assert got.shape == (0,)
    assert got.dtype == bool
