"""Граница работ, не сомкнутая на несколько метров, - всё ещё граница (Нижние Поля: 3,4 м)."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString

from green.application.constraints import boundary_gaps, work_boundary
from green.domain.objects import Feature, ObjectClass, SourceRef


def _line(coords: list[tuple[float, float]]) -> Feature:
    return Feature(
        ref=SourceRef(file_sha8="0" * 8, xref_hash8="0" * 8, handle="1"),
        layer="Граница Заказа",
        geometry=LineString(coords),
        object_class=ObjectClass.WORK_BOUNDARY,
    )


def _loop(gap: float) -> Feature:
    """Прямоугольник 200 x 40 м, концы разведены на `gap` метров по нижней стороне."""
    return _line([(gap, 0), (200, 0), (200, 40), (0, 40), (0, 0)])


def test_a_loop_open_by_a_few_metres_is_closed_by_a_chord() -> None:
    boundary = work_boundary([_loop(3.4)])

    assert boundary is not None
    assert boundary.area == pytest.approx(200 * 40, rel=0.01)
    assert boundary_gaps([_loop(3.4)]) == [("Граница Заказа", pytest.approx(3.4))]


@pytest.mark.parametrize("gap", [6.0, 40.0])
def test_a_wide_gap_is_not_bridged(gap: float) -> None:
    """Разрыв больше 5 м - не погрешность черчения: граница остаётся ненайденной."""
    assert work_boundary([_loop(gap)]) is None
    assert boundary_gaps([_loop(gap)]) == []


def test_the_gap_limit_is_relative_on_a_small_contour() -> None:
    """На контуре 12 м разрыв 3 м - четверть длины, а не погрешность."""
    small = _line([(3, 0), (4, 0), (4, 4), (0, 4), (0, 0)])
    assert work_boundary([small]) is None
    assert math.isclose(small.geometry.length, 13.0)
