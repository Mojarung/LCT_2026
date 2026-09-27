"""Подтверждение колец граней линиями материала: ответ разности со всем объединением."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import shapely

from green.application.surface_faces import _covered

DATA = Path(__file__).resolve().parent / "data"
# Координаты порядка московской системы: узлы сшивки округляются, и кольца граней лежат на
# линиях материала только с точностью до шума, как на чертежах улиц.
_ORIGIN = np.array([13_457.0, 7_123.0])


def _network(seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    starts = _ORIGIN + rng.uniform(0, 120, size=(60, 2))
    ends = starts + rng.normal(0, 45, size=(60, 2))
    lines = shapely.linestrings(np.stack([starts, ends], axis=1))
    material = lines[rng.random(len(lines)) < 0.6]
    noded = shapely.union_all(lines)
    polygons, *_ = shapely.polygonize_full(shapely.get_parts(noded))
    rings = shapely.get_exterior_ring(shapely.get_parts(polygons))
    return rings, material


@pytest.mark.parametrize("seed", range(40))
def test_ring_support_matches_the_difference_with_the_whole_union(seed: int) -> None:
    rings, material = _network(seed)
    expected = shapely.is_empty(shapely.difference(rings, shapely.union_all(material)))

    assert _covered(rings, material).tolist() == expected.tolist()


def test_ring_off_its_lines_by_rounding_noise_keeps_the_whole_union_answer() -> None:
    # Кольцо Куликовской (25 м) и 13 линий материала рядом: вершины кольца отходят от линий
    # на 1e-13...1e-10 м. Объединение одних соседей сдвигало узлы, и кольцо теряло
    # подтверждение, которое даёт разность со всем объединением.
    fixture = json.loads((DATA / "surface_ring_noise.json").read_text(encoding="utf-8"))
    ring = shapely.from_wkb(fixture["ring"])
    material = shapely.from_wkb(np.array(fixture["material"], dtype=object))
    expected = bool(shapely.is_empty(shapely.difference(ring, shapely.union_all(material))))

    assert expected
    assert _covered(np.array([ring], dtype=object), material).tolist() == [expected]


def test_every_ring_is_unsupported_without_material_lines() -> None:
    rings, _ = _network(0)

    assert not _covered(rings, np.empty(0, dtype=object)).any()
