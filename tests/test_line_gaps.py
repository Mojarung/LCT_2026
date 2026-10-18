"""Перемычки в разрывах линий-разделителей покрытий (application/line_gaps.py)."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString

from green.application.line_gaps import GAP_M, bridges


def test_gap_between_two_ends_is_closed() -> None:
    lines = [LineString([(0, 0), (10, 0)]), LineString([(11.5, 0), (20, 0)])]

    found = bridges(lines)

    assert len(found) == 1
    assert found[0].length == pytest.approx(1.5)


def test_entrance_wider_than_the_gap_stays_open() -> None:
    lines = [LineString([(0, 0), (10, 0)]), LineString([(10 + GAP_M + 1, 0), (20, 0)])]

    assert bridges(lines) == []


def test_lines_that_already_touch_get_no_bridge() -> None:
    lines = [LineString([(0, 0), (10, 0)]), LineString([(10, 0), (10, 10)])]

    assert bridges(lines) == []


def test_t_junction_end_is_extended_to_the_crossing_line() -> None:
    # Край покрытия не доходит метр до борта.
    lines = [LineString([(0, 0), (20, 0)]), LineString([(10, 10), (10, 1)])]

    found = bridges(lines)

    assert len(found) == 1
    assert found[0].length == pytest.approx(1.0)
    assert found[0].coords[-1] == pytest.approx((10, 0))


def test_parallel_line_ends_are_not_extended_sideways() -> None:
    # Концы параллельной линии смотрят вдоль борта, а не на него.
    lines = [LineString([(0, 0), (20, 0)]), LineString([(5, 1), (15, 1)])]

    assert bridges(lines) == []
