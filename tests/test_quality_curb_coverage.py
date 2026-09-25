"""Analytic curb coverage: independent lengths, not sampling the production raster."""

from __future__ import annotations

import math
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np
import orjson
import pytest
from shapely.geometry import LineString, Polygon, box

from green.application.params import PlanParams
from green.application.quality.site import site_of
from green.application.quality.terms import Layout, dust
from green.domain.norms import PlantingType
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Placement, Species, Verdict

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from green.application.quality.terms import TermResult


def _tree(number: int, x: float, y: float, radius: float, gas: int = 2) -> Placement:
    return Placement(
        placement_id=str(number),
        number=number,
        planting_type=PlantingType.TREE,
        species=Species(str(number), "test", "test", 2 * radius, gas_tolerance=gas),
        x=x,
        y=y,
        verdict=Verdict.ALLOWED,
        checks=(),
    )


def _result(
    trees: list[Placement], lines: list[LineString], boundary: BaseGeometry | None = None
) -> TermResult:
    features = [
        Feature(SourceRef("input", "curb", str(i)), "curb", line, object_class=ObjectClass.CURB)
        for i, line in enumerate(lines)
    ]
    if boundary is not None:
        features.append(
            Feature(
                SourceRef("input", "site", "work"),
                "work",
                boundary,
                object_class=ObjectClass.WORK_BOUNDARY,
            )
        )
    # Геометрия меры: крона над бортом засчитывается целиком (индекс v2 по умолчанию берёт
    # её с коэффициентом dust_crown_factor, здесь проверяется сама длина покрытия).
    params = PlanParams(dust_target=1.0, dust_crown_factor=1.0)
    return dust(Layout.of(trees), site_of(features), params)


@pytest.mark.parametrize(("x", "y", "expected"), [(5, 2, 3.0), (0, 2, 1.5), (5, 2.5, 0.0)])
def test_circle_intersection_has_analytic_length(x: float, y: float, expected: float) -> None:
    result = _result([_tree(1, x, y, 2.5)], [LineString([(0, 0), (10, 0)])])
    assert result.score == pytest.approx(expected / 10)
    assert result.measure["covered_m"] == pytest.approx(expected)
    assert result.deltas[0] == pytest.approx(expected / 10)


def test_overlapping_crowns_use_best_weight_and_exact_removal_loss() -> None:
    trees = [_tree(1, 5, 0, 3, 1), _tree(2, 7, 0, 3, 2)]
    result = _result(trees, [LineString([(0, 0), (10, 0)])])
    assert result.score == pytest.approx(0.7)
    assert result.measure["covered_m"] == pytest.approx(8)
    assert result.deltas == pytest.approx([0.1, 0.4])
    # Public report JSON must contain ordinary floats, not numpy scalars.
    orjson.dumps({"score": result.score, "measure": result.measure})


@pytest.mark.parametrize("angle", [0, 37, 113])
@pytest.mark.parametrize("shift", [0, 1_000_000])
@pytest.mark.parametrize("segments", [1, 7, 100])
def test_score_is_stable_under_rigid_transforms_and_fragmentation(
    angle: int, shift: int, segments: int
) -> None:
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def xy(x: float, y: float) -> tuple[float, float]:
        return shift + x * c - y * s, -shift + x * s + y * c

    # Repeat reversed geometry too: representation must not double its physical length.
    points = [xy(i * 10 / segments, 0) for i in range(segments + 1)]
    lines = [LineString([a, b]) for a, b in pairwise(points)]
    lines += [LineString(list(reversed(points)))]
    result = _result([_tree(1, *xy(5, 2), 2.5)], lines)
    assert result.score == pytest.approx(0.3, abs=1e-8)
    assert result.measure["curb_m"] == pytest.approx(10, abs=1e-6)
    assert result.measure["covered_m"] == pytest.approx(3, abs=1e-6)


def test_clipping_happens_before_measuring_curb_length() -> None:
    result = _result([_tree(1, 5, 2, 2.5)], [LineString([(0, 0), (10, 0)])], box(2, -5, 8, 5))
    assert result.score == pytest.approx(0.5)
    assert result.measure["curb_m"] == pytest.approx(6)


def test_disconnected_lines_keep_uncovered_length_in_denominator() -> None:
    result = _result(
        [_tree(1, 5, 2, 2.5)],
        [LineString([(0, 0), (10, 0)]), LineString([(0, 20), (10, 20)])],
    )
    assert result.score == pytest.approx(0.15)
    assert result.measure["curb_m"] == pytest.approx(20)


def test_zero_weight_crown_still_counts_geometric_coverage() -> None:
    result = _result([_tree(1, 5, 2, 2.5, 0)], [LineString([(0, 0), (10, 0)])])
    assert result.score == 0
    assert result.measure["covered_m"] == pytest.approx(3)
    assert result.deltas[0] == 0


def test_boundary_hole_and_tangent_parts_add_no_connecting_segment() -> None:
    boundary = box(0, -5, 10, 5).difference(box(4, -1, 6, 1))
    lines = [LineString([(-1, 0), (11, 0)]), LineString([(-1, 4), (0, 5), (-1, 6)])]
    result = _result([_tree(1, 5, 0, 1)], lines, boundary)
    # Micrometre clipping margin affects the four cut ends and the tangent corner.
    assert result.measure["curb_m"] == pytest.approx(8, abs=1e-5)
    assert result.score == pytest.approx(0, abs=1e-6)


def test_equal_weight_overlap_has_no_loss_until_one_crown_is_removed() -> None:
    trees = [_tree(1, 5, 2, 2.5), _tree(2, 5, 2, 2.5)]
    result = _result(trees, [LineString([(0, 0), (10, 0)])])
    assert result.score == pytest.approx(0.3)
    assert result.deltas == pytest.approx([0, 0])


def test_empty_plan_still_scores_zero_on_a_known_curb() -> None:
    result = _result([], [LineString([(0, 0), (0.1, 0)])])
    assert result.score == 0
    assert result.measure["curb_m"] == pytest.approx(0.1)
    assert result.measure["covered_m"] == 0


@pytest.mark.parametrize("angle", [0, 37, 113])
@pytest.mark.parametrize("shift", [0, 1_000_000])
@pytest.mark.parametrize("unit_m", [1, 0.001, 0.3048])
def test_curb_on_boundary_is_not_cut_away_by_coordinate_roundoff(
    angle: int, shift: int, unit_m: float
) -> None:
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))

    def xy(x: float, y: float) -> tuple[float, float]:
        return (
            (shift + x * c - y * s) / unit_m * unit_m,
            (-shift + x * s + y * c) / unit_m * unit_m,
        )

    boundary = Polygon([xy(0, 0), xy(120, 0), xy(120, 60), xy(0, 60)])
    curb = LineString([xy(0, 20), xy(120, 20), xy(120, 55), xy(0, 55), xy(0, 20)])
    features = [
        Feature(SourceRef("in", "c", "c"), "curb", curb, object_class=ObjectClass.CURB),
        Feature(
            SourceRef("in", "b", "b"), "work", boundary, object_class=ObjectClass.WORK_BOUNDARY
        ),
    ]
    site = site_of(features)
    assert site.boundary is not None
    assert site.boundary.equals(boundary)
    segments = site.curb_segments
    assert np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1).sum() == pytest.approx(
        310, abs=1e-5
    )


def test_quality_clip_tolerance_does_not_include_a_curb_one_mm_outside() -> None:
    result = _result(
        [_tree(1, 0, 5, 2.5)], [LineString([(-0.001, 0), (-0.001, 10)])], box(0, 0, 10, 10)
    )
    assert result.score is None
