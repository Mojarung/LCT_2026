"""Framed shrub groups fit the same physical strip after exported-coordinate rounding."""

from __future__ import annotations

import math

import numpy as np
import pytest
import shapely
from scipy.spatial.distance import cdist, pdist
from shapely import affinity
from shapely.geometry import box

from green.application.params import PlanParams
from green.application.placement import GreedyPlantingStrategy
from green.domain.norms import PlantingType, RuleBook
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import LifeForm, Species


def _group(angle: float, shift: float, half_width: float) -> tuple[np.ndarray, np.ndarray]:
    area = affinity.translate(
        affinity.rotate(box(-2, -half_width, 2, half_width), angle, origin=(0, 0)), shift, -shift
    )
    features = [
        Feature(SourceRef("test", "test", kind.value), "test", area, object_class=kind)
        for kind in (ObjectClass.LAWN, ObjectClass.WORK_BOUNDARY)
    ]
    params = PlanParams(
        planting_type=PlantingType.SHRUB,
        spacing_m=1,
        require_utility_data=False,
        lawn_anchor="soil",
        lawn_rotation_deg=angle,
    )
    placements = GreedyPlantingStrategy().shrub_groups(
        features,
        (),
        RuleBook({}, (), "synthetic"),
        Species("test", "Тест", "Test", 1, life_form=LifeForm.SHRUB_MEDIUM),
        params,
        centers=[(shift, -shift)],
    )
    xy = np.array([(p.x, p.y) for p in placements]).reshape(-1, 2)
    assert np.all(shapely.contains(area, shapely.points(xy)))
    assert np.all(shapely.distance(shapely.points(xy), area.boundary) >= 0.5)
    assert pdist(xy).min() >= 1 - 1e-9  # exported footprints really do not overlap
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    return xy, (xy - [shift, -shift]) @ np.array([[c, -s], [s, c]])


@pytest.mark.parametrize("angle", [0, 21.2, 45, 77, 113, 179])
@pytest.mark.parametrize("shift", [0, 1_000_000])
@pytest.mark.parametrize("half_width", [0.6, 2.0])
def test_framed_groups_keep_members_and_positions_in_rotated_soil(
    angle: float, shift: float, half_width: float
) -> None:
    _, expected = _group(0, 0, half_width)
    _, actual = _group(angle, shift, half_width)
    assert len(expected) == (3 if half_width < 1 else 9)
    assert len(actual) == len(expected)
    # World coordinates round to 1 mm: inverse rotation preserves the 0.71 mm error bound.
    assert cdist(actual, expected).min(axis=1).max() <= math.sqrt(2) * 0.0005 + 1e-9
