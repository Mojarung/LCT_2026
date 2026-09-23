"""Curb rows depend on nearby physical geometry, not CAD vertex direction or remote tails."""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, box

from green.application.params import PlanParams
from green.application.placement import GreedyPlantingStrategy, _curb_candidates, _curb_lines
from green.domain.norms import RuleBook
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Plan, Species


def _feature(kind: ObjectClass, geometry: shapely.Geometry, number: int = 0) -> Feature:
    return Feature(SourceRef("test", "test", str(number)), "test", geometry, object_class=kind)


def _candidates(lines: list[LineString]) -> list[tuple[int, float, float]]:
    features = [_feature(ObjectClass.CURB, line, i) for i, line in enumerate(lines)]
    candidates = _curb_candidates(_curb_lines(features), PlanParams())
    return [(p.station, round(p.x, 6), round(p.y, 6)) for p in candidates]


@pytest.mark.parametrize("closed", [False, True])
@pytest.mark.parametrize("representation", ["reverse", "split", "duplicate", "start"])
@pytest.mark.parametrize("angle", [0, 37, 113])
@pytest.mark.parametrize("shift", [0, 1_000_000])
def test_curb_candidates_keep_order_when_only_representation_changes(
    *, closed: bool, representation: str, angle: float, shift: float
) -> None:
    coords = [(0, 0), (43, 0), (67, 10), (100, 10)]
    if closed:
        coords += [(100, 35), (0, 35), coords[0]]
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    coords = [(shift + x * c - y * s, -shift + x * s + y * c) for x, y in coords]
    original = LineString(coords)
    if representation == "reverse":
        changed = [LineString(coords[::-1])]
    elif representation == "split":
        changed = [LineString([b, a]) for a, b in pairwise(coords)]
    elif representation == "duplicate":
        changed = [LineString(coords[::-1]), original, original]
    elif closed:
        ring = coords[:-1]
        changed = [LineString(ring[2:] + ring[:2] + [ring[2]])]
    else:
        changed = [original]
    assert _candidates(changed) == _candidates([original])


def _plan(tail: float, y: float = 4, *, remote_branch: bool = False) -> Plan:
    boundary = box(0, 0, 100, 30)
    features = [
        _feature(ObjectClass.WORK_BOUNDARY, boundary),
        _feature(ObjectClass.LAWN, boundary),
        _feature(ObjectClass.CURB, LineString([(-tail, y), (100 + tail, y)])),
    ]
    if remote_branch:
        features.append(_feature(ObjectClass.CURB, LineString([(-50, y), (-50, 100)]), 2))
    return GreedyPlantingStrategy().plan(
        features,
        (),
        RuleBook({}, (), "synthetic"),
        Species("test", "test", "test", 4),
        PlanParams(
            modes=("alley",),
            require_utility_data=False,
            placement_solver="greedy",
            zones=False,
            curb_offsets_m=(2, 3),
        ),
    )


def test_distant_curb_continuation_does_not_generate_distant_stations() -> None:
    plan = _plan(10_000)
    assert plan.stats["alley_candidates"] <= 80
    assert len(plan.placements) >= 12
    for p in plan.placements:
        point = shapely.Point(p.x, p.y)
        assert box(0, 0, 100, 30).contains(point)
        assert box(0, 0, 100, 30).boundary.distance(point) >= 1.6


def test_continuation_and_branch_beyond_influence_do_not_move_the_row() -> None:
    baseline = _plan(100)
    changed = _plan(317, remote_branch=True)
    np.testing.assert_array_equal(
        [(p.x, p.y) for p in changed.placements], [(p.x, p.y) for p in baseline.placements]
    )


def test_curb_just_outside_work_boundary_can_still_generate_inside_row() -> None:
    plan = _plan(100, -1)
    assert len(plan.placements) >= 12
    assert all(p.y == 2 for p in plan.placements)


def test_far_curb_generates_no_candidates() -> None:
    plan = _plan(100, -10)
    assert plan.stats["alley_candidates"] == 0
    assert not plan.placements


def test_extremely_long_input_line_is_clipped_before_station_allocation() -> None:
    features = [_feature(ObjectClass.CURB, LineString([(-1e12, 4), (1e12, 4)]))]
    lines = _curb_lines(features, box(0, 0, 100, 30), 3.002)
    assert sum(line.length for line in lines) < 107
    # Allocate candidates only after the independent bounded-length assertion.
    assert len(_curb_candidates(lines, PlanParams())) <= 120


def test_empty_offsets_do_not_allocate_stations() -> None:
    assert not _curb_candidates(
        [LineString([(-1e12, 0), (1e12, 0)])], PlanParams(curb_offsets_m=())
    )


def test_disconnected_work_sites_do_not_generate_a_row_between_them() -> None:
    boundary = shapely.union_all([box(0, 0, 30, 20), box(1000, 0, 1030, 20)])
    features = [_feature(ObjectClass.CURB, LineString([(-1e9, 4), (1e9, 4)]))]
    lines = _curb_lines(features, boundary, 3.002)
    assert len(lines) == 2
    assert sum(line.length for line in lines) < 73
    assert all(not line.intersects(box(100, -100, 900, 100)) for line in lines)


def test_tangent_point_after_clipping_is_not_a_row() -> None:
    boundary = box(0, 0, 100, 30)
    features = [_feature(ObjectClass.CURB, LineString([(-10, 10), (0, 0), (-10, -10)]))]
    assert not _curb_lines(features, boundary)


def test_concentric_curbs_keep_traversal_order_when_entities_are_reordered() -> None:
    outer = LineString(box(-50, -25, 50, 25).exterior.coords)
    inner = LineString(box(-30, -15, 30, 15).exterior.coords)
    assert _candidates([inner, outer]) == _candidates([outer, inner])
