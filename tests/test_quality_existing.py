"""Индекс с существующими насаждениями: тень, пылезащита и ярусность считают прирост."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from shapely.geometry import LineString, Point, box
from test_quality import LAWN, LIME, SPIREA, _place, _plan

from green.application.params import PlanParams
from green.application.quality import Site, evaluate, site_of
from green.domain.objects import Feature, ObjectClass, SourceRef

if TYPE_CHECKING:
    from green.domain.planting import Plan

PARAMS = PlanParams()
EXISTING = (100.0, 0.0)


def _site(*trunks: tuple[float, float]) -> Site:
    features = [
        Feature(
            SourceRef("f", "x", "1"),
            "граница",
            box(0.0, -10.0, 200.0, 10.0),
            object_class=ObjectClass.WORK_BOUNDARY,
        ),
        Feature(
            SourceRef("f", "x", "2"),
            "борт",
            LineString([(0.0, -2.0), (200.0, -2.0)]),
            object_class=ObjectClass.CURB,
        ),
    ]
    features += [
        Feature(
            SourceRef("f", "x", f"t{i}"),
            "деревья",
            Point(x, y),
            object_class=ObjectClass.EXISTING_TREE,
            symbol=f"s{i}",
        )
        for i, (x, y) in enumerate(trunks)
    ]
    return site_of(features)


def _term(plan: Plan, key: str, site: Site):  # noqa: ANN202
    return next(t for t in evaluate(plan, site, PARAMS).terms if t.key == key)


def _with(plan: Plan, *extra) -> Plan:  # noqa: ANN002
    return replace(plan, placements=(*plan.placements, *extra))


def test_new_crown_inside_an_existing_one_adds_no_shade() -> None:
    site = _site(EXISTING)
    base = _plan()
    under = _with(base, _place(20, 100.5, 0.0, LIME, note=LAWN))
    assert _term(under, "canopy", site).measure["m2"] == _term(base, "canopy", site).measure["m2"]


def test_existing_crowns_count_in_shade() -> None:
    base = _plan()
    assert (
        _term(base, "canopy", _site(EXISTING)).measure["m2"]
        > _term(base, "canopy", _site()).measure["m2"]
    )
    assert _term(base, "canopy", _site(EXISTING)).measure["existing_m2"] > 0


def test_shrub_at_the_curb_under_an_existing_crown_adds_dust_protection() -> None:
    site = _site(EXISTING)
    base = _plan()
    shrub = _with(base, _place(20, 100.0, -1.0, SPIREA, note="группа кустарников"))
    assert _term(shrub, "dust", site).score > _term(base, "dust", site).score
    assert _term(base, "dust", site).measure["existing_covered_m"] > 0


def test_shrub_under_an_existing_tree_is_a_second_tier() -> None:
    site = _site(EXISTING)
    base = _plan()
    shrub = _with(base, _place(20, 101.0, 0.5, SPIREA, note="кустарник под кроной"))
    before = _term(base, "tiers", site).measure["covered"]
    assert _term(shrub, "tiers", site).measure["covered"] == before + 1
    assert _term(shrub, "tiers", site).measure["existing"] == 1


def test_adding_a_planting_never_lowers_the_index_with_existing_trees() -> None:
    site = _site(EXISTING, (30.0, 3.0), (150.0, -3.0))
    base = _plan()
    index = evaluate(base, site, PARAMS).index
    for extra in (
        _place(20, 100.5, 0.0, LIME, note=LAWN),
        _place(21, 180.0, 5.0, LIME, note=LAWN),
        _place(22, 150.0, -1.0, SPIREA, note="группа кустарников"),
    ):
        assert evaluate(_with(base, extra), site, PARAMS).index >= index - 1e-9


def test_one_shrub_under_two_pseudo_trunks_is_one_tier() -> None:
    site = _site(EXISTING, (101.7, 0.0))
    shrub = _with(_plan(), _place(20, 101.0, 0.5, SPIREA, note="кустарник под кроной"))
    assert _term(shrub, "tiers", site).measure["existing"] == 1
