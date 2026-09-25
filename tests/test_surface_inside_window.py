"""Windowed material rasterization agrees with whole-grid point containment."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon, box

from green.application.surfaces import _inside


@pytest.mark.parametrize("shift", [(0.0, 0.0), (1_000_000.0, 2_000_000.0)])
def test_sparse_parts_and_holes_match_full_grid(shift: tuple[float, float]) -> None:
    x, y = shift
    area = MultiPolygon(
        [
            Polygon(
                [(x + 0.5, y + 0.5), (x + 8.5, y + 0.5), (x + 8.5, y + 8.5), (x + 0.5, y + 8.5)],
                holes=[[(x + 2, y + 2), (x + 5, y + 2), (x + 5, y + 5), (x + 2, y + 5)]],
            ),
            box(x + 31.25, y + 24.25, x + 32.75, y + 25.75),
        ]
    )
    origin, cell, shape = (x, y), 0.5, (60, 80)
    rows, cols = np.mgrid[: shape[0], : shape[1]]
    expected = shapely.contains_xy(
        area,
        origin[0] + (cols + 0.5) * cell,
        origin[1] + (rows + 0.5) * cell,
    )
    np.testing.assert_array_equal(_inside(area, origin, cell, shape), expected)


def test_outside_and_empty_parts_remain_false() -> None:
    shape = (20, 20)
    assert not _inside(box(100, 100, 101, 101), (0, 0), 1.0, shape).any()
    assert not _inside(Polygon(), (0, 0), 1.0, shape).any()
