"""Equivalent physical groups with stable identities must not depend on drawing axes."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from green.application.assortment.structures import build_structures
from green.application.placement import MODE_LABELS
from green.domain.norms import PlantingType
from green.domain.planting import Placement, Species, Verdict


def _group(shape: str) -> list[Placement]:
    points = {
        "rectangle": [(3 * x, 3 * y) for x in range(11) for y in range(3)],
        "square": [(3 * x, 3 * y) for x in range(5) for y in range(5)],
        "row": [(3 * x, 0) for x in range(25)],
    }[shape]
    return [
        Placement(
            placement_id=f"p-{i:03d}",
            number=i + 1,
            planting_type=PlantingType.TREE,
            species=Species("test", "Тест", "Test", 4),
            x=x,
            y=y,
            verdict=Verdict.ALLOWED,
            checks=(),
            notes=(MODE_LABELS["lawn"],),
        )
        for i, (x, y) in enumerate(points)
    ]


@pytest.mark.parametrize("shape", ["rectangle", "square", "row"])
@pytest.mark.parametrize("angle", [0, 17, 45, 97, 179, 271])
@pytest.mark.parametrize("shift", [0, 1_000_000])
@pytest.mark.parametrize("mirror", [1, -1])
def test_same_physical_patches_under_rigid_transform(
    shape: str, angle: float, shift: float, mirror: int
) -> None:
    plants = _group(shape)
    expected = build_structures(plants, 3, 6)
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    transformed = [
        replace(p, x=shift + mirror * p.x * c - p.y * s, y=-shift + mirror * p.x * s + p.y * c)
        for p in reversed(plants)
    ]
    actual = build_structures(transformed, 3, 6)
    assert actual == expected
    assert all(len(p.placement_ids) <= 6 for p in actual)


def test_coincident_members_are_partitioned_without_losing_identities() -> None:
    plants = [replace(p, x=1e6, y=-1e6) for p in _group("row")]
    structures = build_structures(plants, 3, 6)
    assert structures == build_structures(plants[::-1], 3, 6)
    assert all(len(s.placement_ids) <= 6 for s in structures)
    assert sorted(pid for s in structures for pid in s.placement_ids) == sorted(
        p.placement_id for p in plants
    )
