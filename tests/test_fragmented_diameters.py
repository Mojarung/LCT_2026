"""Equivalent pipe segmentations retain wall clearance without merging other pipes."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, Point

from green.application.constraints import ConstraintIndex
from green.application.diameters import assign_diameters
from green.domain.norms import (
    Citation,
    CitationStatus,
    DistanceRule,
    MeasureTo,
    PlantingType,
    Severity,
)
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel
from green.domain.planting import Verdict


def _line(
    start: tuple[float, float],
    end: tuple[float, float],
    handle: str,
    diameter: float | None = None,
) -> Feature:
    return Feature(
        SourceRef("00000001", "00000000", handle),
        "Водопровод",
        LineString([start, end]),
        object_class=ObjectClass.UTILITY_WATER,
        diameter_m=diameter,
    )


def _label(y: float, diameter: int) -> TextLabel:
    return TextLabel(
        SourceRef("00000001", "00000000", f"label-{y}"),
        "Водопровод",
        5.0,
        y + 0.5,
        f"d={diameter}ст.",
    )


def _rule() -> DistanceRule:
    return DistanceRule(
        "water-wall",
        ObjectClass.UTILITY_WATER,
        PlantingType.TREE,
        2.0,
        MeasureTo.OUTER_WALL,
        Severity.FORBID,
        Citation("test", "test", "test", CitationStatus.UNVERIFIED),
    )


def _pipe(y: float) -> tuple[Feature, ...]:
    return tuple(_line((x, y), (x + 1, y), f"{y}-{x}") for x in range(2, 38))


def test_segmentation_preserves_wall_clearance() -> None:
    fragmented = _pipe(10.0)
    single = (_line((2.0, 10.0), (38.0, 10.0), "single"),)
    for source in (single, fragmented):
        assigned = assign_diameters(source, (_label(10.0, 400),), 3.0)
        assert all(feature.diameter_m == 0.4 for feature in assigned)
        result = ConstraintIndex(assigned, [_rule()], require_utility_data=True).evaluate(
            np.array([Point(30, 12.05)], dtype=object)
        )
        assert result.clearance[0, 0] == pytest.approx(1.85)
        assert result.verdict(0) is Verdict.FORBIDDEN


def test_separate_parallel_pipes_keep_their_own_diameters() -> None:
    assigned = assign_diameters(
        (*_pipe(10.0), *_pipe(13.0)), (_label(10.0, 400), _label(13.0, 100)), 3.0
    )
    assert {feature.diameter_m for feature in assigned[:36]} == {0.4}
    assert {feature.diameter_m for feature in assigned[36:]} == {0.1}
    result = ConstraintIndex(assigned, [_rule()], require_utility_data=True).evaluate(
        np.array([Point(30, 15.1)], dtype=object)
    )
    assert result.clearance[0, 0] == pytest.approx(2.05)
    assert result.verdict(0) is Verdict.ALLOWED


def _negative_cases() -> dict[str, tuple[Feature, ...]]:
    seed = _line((0, 0), (1, 0), "seed", 0.4)
    next_segment = _line((1, 0), (2, 0), "next")
    return {
        "branch": (seed, next_segment, _line((1, 0), (1, 1), "branch")),
        "interior-crossing": (
            seed,
            _line((1, 0), (3, 0), "long"),
            _line((2, -1), (2, 1), "cross"),
        ),
        "t-junction": (
            seed,
            _line((1, 0), (3, 0), "long"),
            _line((2, 0), (2, 1), "tee"),
        ),
        "conflicting-diameters": (
            seed,
            next_segment,
            _line((2, 0), (3, 0), "other-diameter", 0.2),
        ),
        "gap": (seed, _line((1.000001, 0), (2, 0), "gap")),
        "different-layer": (seed, replace(next_segment, layer="Водопровод проектный")),
        "different-class": (
            seed,
            replace(next_segment, object_class=ObjectClass.UTILITY_GAS),
        ),
        "loop": (
            seed,
            _line((1, 0), (0, 1), "diagonal"),
            _line((0, 1), (0, 0), "close"),
        ),
        "overlap": (seed, _line((0, 0), (1, 0), "duplicate")),
        "parallel": (seed, _line((0, 0.01), (1, 0.01), "parallel")),
        "uncertain-geometry": (seed, replace(next_segment, geometry_error_m=0.1)),
        "empty": (seed, replace(next_segment, geometry=LineString())),
    }


@pytest.mark.parametrize("case", tuple(_negative_cases()))
def test_ambiguous_or_disconnected_geometry_does_not_inherit(case: str) -> None:
    source = _negative_cases()[case]
    assigned = assign_diameters(source, (), 3.0)
    assert [feature.diameter_m for feature in assigned] == [
        feature.diameter_m for feature in source
    ]
    assert [feature.ref for feature in assigned] == [feature.ref for feature in source]
    assert [feature.geometry.wkb for feature in assigned] == [
        feature.geometry.wkb for feature in source
    ]


def test_chain_fill_cannot_add_allowed_points() -> None:
    # Explicit baseline assignment fixture: the original nearest-only algorithm
    # has assigned the diameter to one primitive and there are no further labels.
    baseline = (replace(_pipe(10.0)[0], diameter_m=0.4), *_pipe(10.0)[1:])
    proposed = assign_diameters(baseline, (), 3.0)
    x, y = np.meshgrid(np.linspace(0, 40, 81), np.linspace(5, 15, 101))
    points = shapely.points(np.column_stack((x.ravel(), y.ravel())))
    before = ConstraintIndex(baseline, [_rule()], require_utility_data=True).evaluate(points)
    after = ConstraintIndex(proposed, [_rule()], require_utility_data=True).evaluate(points)
    assert np.all(after.clearance <= before.clearance + 1e-12)
    assert all(
        after.verdict(index) is not Verdict.ALLOWED or before.verdict(index) is Verdict.ALLOWED
        for index in range(len(points))
    )


@pytest.mark.parametrize("diameter", [float("nan"), float("inf")])
def test_nonfinite_diameter_is_not_propagated(diameter: float) -> None:
    source = (
        _line((0, 0), (1, 0), "seed", diameter),
        _line((1, 0), (2, 0), "unknown"),
    )
    assigned = assign_diameters(source, (), 3.0)
    assert assigned[0] is source[0]
    assert assigned[1].diameter_m is None
