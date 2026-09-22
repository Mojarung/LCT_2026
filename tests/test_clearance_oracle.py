"""Spatial index against a brute-force geometric oracle, including different pipe radii."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point

from green.application.constraints import ConstraintIndex
from green.domain.norms import Citation, DistanceRule, MeasureTo, PlantingType, Severity
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Verdict


def pipe(x: float, radius: float, handle: str) -> Feature:
    return Feature(
        SourceRef("file0000", "00000000", handle),
        "water",
        LineString([(x, -100), (x, 100)]),
        object_class=ObjectClass.UTILITY_WATER,
        diameter_m=radius * 2,
    )


def rule(measure: MeasureTo = MeasureTo.OUTER_WALL) -> DistanceRule:
    return DistanceRule(
        "R-TEST-TREE-001",
        ObjectClass.UTILITY_WATER,
        PlantingType.TREE,
        2.0,
        measure,
        Severity.FORBID,
        Citation("PROJECT", "synthetic", "", "unverified"),
    )


def test_farther_axis_can_have_the_nearest_pipe_wall() -> None:
    pipes = [pipe(2.5, 0.1, "thin"), pipe(3.0, 1.5, "wide")]
    index = ConstraintIndex(pipes, [rule()], require_utility_data=True)
    batch = index.evaluate(shapely.points([(0, 0)]))
    assert batch.clearance[0, 0] == pytest.approx(1.5)
    assert batch.checks(0)[0].nearest == pipes[1].ref
    assert batch.verdict(0) is Verdict.FORBIDDEN


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("measure", [MeasureTo.OUTER_WALL, MeasureTo.AXIS])
def test_index_matches_exhaustive_distances(seed: int, measure: MeasureTo) -> None:
    rng = np.random.default_rng(seed)
    pipes = [
        pipe(float(x), float(r), str(i))
        for i, (x, r) in enumerate(
            zip(rng.uniform(-30, 30, 25), rng.uniform(0, 2, 25), strict=True)
        )
    ]
    # Slanted and finite segments prevent this from only testing parallel lines.
    pipes += [replace(pipe(0, 1, "slanted"), geometry=LineString([(-20, -10), (20, 30)]))]
    points = [Point(float(x), float(y)) for x, y in rng.uniform(-45, 45, (60, 2))]
    batch = ConstraintIndex(pipes, [rule(measure)], require_utility_data=True).evaluate(
        np.array(points, dtype=object)
    )
    expected = [
        max(
            0,
            min(
                p.distance(f.geometry)
                - ((f.diameter_m or 0) / 2 if measure is MeasureTo.OUTER_WALL else 0)
                for f in pipes
            ),
        )
        for p in points
    ]
    np.testing.assert_allclose(batch.clearance[0], expected, atol=1e-10)
    assert [batch.verdict(i) is Verdict.ALLOWED for i in range(len(points))] == [
        d >= 2.0 - 1e-3 for d in expected
    ]
