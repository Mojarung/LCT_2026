"""A closed/fragmented curb has an axis even when its endpoint displacement is zero."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest
from shapely.geometry import LineString, box

from green.application.params import PlanParams
from green.application.portfolio import _curb_angle, choose_plan
from green.application.validation import PlanValidation
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Plan
from green.domain.quality import PlanQuality


def _features(lines: list[LineString]) -> list[Feature]:
    return [
        Feature(SourceRef("source", "curb", str(i)), "curb", line, object_class=ObjectClass.CURB)
        for i, line in enumerate(lines)
    ]


def _rectangle(angle: float, shift: float, *, square: bool = False) -> list[tuple[float, float]]:
    c, s = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    top = 120 if square else 35
    return [
        (shift + x * c - y * s, -shift + x * s + y * c)
        for x, y in ((0, 0), (120, 0), (120, top), (0, top), (0, 0))
    ]


@pytest.mark.parametrize("angle", [0, 37, 113, 179.9])
@pytest.mark.parametrize("shift", [0, 1_000_000])
@pytest.mark.parametrize("representation", ["closed", "split", "reversed", "duplicate"])
def test_closed_curb_axis_is_independent_of_representation(
    angle: float, shift: float, representation: str
) -> None:
    points = _rectangle(angle, shift)
    if representation == "split":
        lines = [LineString([a, b]) for a, b in pairwise(points)]
    elif representation == "reversed":
        lines = [LineString(points[::-1])]
    elif representation == "duplicate":
        lines = [LineString(points), LineString(points[::-1])]
    else:
        lines = [LineString(points)]
    found = _curb_angle(_features(lines))
    assert found is not None
    assert abs((found - angle + 90) % 180 - 90) < 1e-6


def test_fragment_count_does_not_outvote_physical_length() -> None:
    # One horizontal curb is 120 m; 100 vertical pieces together are only 35 m.
    lines = [LineString([(0, 0), (120, 0)])]
    lines += [LineString([(0, i * 0.35), (0, (i + 1) * 0.35)]) for i in range(100)]
    assert _curb_angle(_features(lines)) == pytest.approx(0)


@pytest.mark.parametrize("angle", [0, 37, 113])
def test_isotropic_square_does_not_invent_an_axis(angle: float) -> None:
    assert _curb_angle(_features([LineString(_rectangle(angle, 1_000_000, square=True))])) is None


def test_degenerate_curbs_do_not_supply_an_orientation() -> None:
    assert _curb_angle(_features([LineString([(0, 0), (0, 0)])])) is None


@pytest.mark.parametrize("x", [40, 1000])
def test_curb_outside_the_work_boundary_cannot_choose_the_street_axis(x: int) -> None:
    features = _features(
        [
            LineString(_rectangle(0, 0)),
            LineString([(x, -1000), (x, 1000)]),
        ]
    )
    features.append(
        Feature(
            SourceRef("source", "work", "w"),
            "work",
            box(-1, -1, 121, 36),
            object_class=ObjectClass.WORK_BOUNDARY,
        )
    )
    assert _curb_angle(features) == pytest.approx(0)


def test_closed_curb_adds_a_complete_valid_aligned_alternative() -> None:
    seen = []

    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        seen.append(params.lawn_rotation_deg)
        # Поворот по борту без привязки к грунту: сетка на грунте (soil_frame) тоже повёрнута,
        # но здесь проверяется именно вариант aligned.
        aligned = abs(params.lawn_rotation_deg - 37) < 1e-6 and params.lawn_anchor != "soil"
        score = 0.8 if aligned else 0.3
        return Plan((), (), quality=PlanQuality(score, "", (), 0, {}, ())), PlanValidation(0, ())

    plan, validation = choose_plan(
        build,
        PlanParams(placement_solver="portfolio"),
        _features([LineString(_rectangle(37, 1_000_000))]),
    )
    assert validation.ok
    assert any(abs(angle - 37) < 1e-6 for angle in seen)
    assert plan.portfolio is not None
    # При равном индексе выигрывает посчитанный раньше: объединённый отбор идёт первым.
    assert plan.portfolio.chosen == "aligned_joint"
