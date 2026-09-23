"""A lawn lattice follows its declared physical frame, not the display raster bbox."""

from __future__ import annotations

import math

import numpy as np
import pytest
from shapely import affinity
from shapely.geometry import Polygon, box

from green.application.params import PlanParams
from green.application.placement import _lawn_candidates
from green.application.surfaces import Material, SurfaceMap


def _surface(angle: float, shift: float, padding: float = 1) -> SurfaceMap:
    area = Polygon(
        [(0, 0), (73, 0), (73, 31), (43, 31), (43, 24), (0, 24)],
        holes=[[(20, 6), (26, 6), (26, 12), (20, 12)]],
    )
    area = affinity.translate(affinity.rotate(area, angle, origin=(0, 0)), shift, -shift)
    x0, y0, x1, y1 = area.bounds
    cell = 0.5
    grid = np.full(
        (math.ceil((y1 - y0 + 2 * padding) / cell), math.ceil((x1 - x0 + 2 * padding) / cell)),
        int(Material.UNKNOWN),
        dtype=np.int8,
    )
    return SurfaceMap(grid, (x0 - padding, y0 - padding), cell, 0, 0, soil_area=area)


def _points(
    angle: float, shift: float, phase: tuple[float, float], padding: float = 1
) -> np.ndarray:
    params = PlanParams(lawn_rotation_deg=angle, lawn_phase=phase, lawn_anchor="soil")
    candidates = _lawn_candidates(_surface(angle, shift, padding), params)
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    xy = np.array([(p.x - shift, p.y + shift) for p in candidates]).reshape(-1, 2)
    local = np.round(xy @ np.array([[c, -s], [s, c]]), 6)
    return local[np.lexsort((local[:, 0], local[:, 1]))]


@pytest.mark.parametrize("angle", [0, 21.2, 47.5, 113, 179, 270])
@pytest.mark.parametrize("shift", [0, 1_000_000])
@pytest.mark.parametrize("phase", [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5)])
def test_rotated_lawn_has_the_same_candidates_in_its_frame(
    angle: float, shift: float, phase: tuple[float, float]
) -> None:
    expected = _points(0, 0, phase)
    assert len(expected) > 40
    actual = _points(angle, shift, phase)
    np.testing.assert_allclose(actual, expected, atol=1e-6)


def test_display_extent_does_not_move_an_explicit_lawn_lattice() -> None:
    np.testing.assert_allclose(_points(37, 1e6, (0.5, 0), 50), _points(37, 1e6, (0.5, 0)))


def test_empty_soil_area_does_not_produce_candidates() -> None:
    surface = SurfaceMap(
        np.zeros((5, 5), dtype=np.int8), (0, 0), 0.5, 0, 0, soil_area=box(0, 0, 0, 0)
    )
    assert not _lawn_candidates(surface, PlanParams(lawn_anchor="soil"))
