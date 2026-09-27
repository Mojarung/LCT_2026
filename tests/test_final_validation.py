"""Mutation checks: independent final validation must catch stale/forged success traces."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import pytest
from shapely.geometry import LineString
from test_pipeline_synthetic import ROOT, _street

from green.application.params import PlanParams, step_with_tolerance
from green.application.use_case import PlanRequest
from green.application.validation import trim_to_quotas, validate_plan
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.norms import (
    Citation,
    CitationStatus,
    DistanceRule,
    MeasureTo,
    PlantingType,
    RuleBook,
    Severity,
)
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import (
    CheckOutcome,
    LifeForm,
    Placement,
    Plan,
    RuleCheck,
    Species,
    Verdict,
)

if TYPE_CHECKING:
    from pathlib import Path

TREE = Species("test_tree", "Дерево", "Testus tree", 3, height_m=4, crown_mature_m=3)
PARAMS = PlanParams(
    require_soil=False,
    require_work_boundary=False,
    require_utility_data=False,
    planting_radius_m=0,
    shrub_planting_radius_m=0,
    assortment_mode="single",
)


def pipe(x: float, diameter: float, index: int = 0) -> Feature:
    return Feature(
        SourceRef("00000000", "00000000", str(index)),
        "unknown names are irrelevant after mapping",
        LineString([(x, -100), (x, 100)]),
        object_class=ObjectClass.UTILITY_WATER,
        diameter_m=diameter,
    )


def rule(
    *, severity: Severity = Severity.FORBID, measure: MeasureTo = MeasureTo.OUTER_WALL
) -> DistanceRule:
    return DistanceRule(
        "r",
        ObjectClass.UTILITY_WATER,
        PlantingType.TREE,
        2,
        measure,
        severity,
        Citation("test", "test", "Synthetic", CitationStatus.UNVERIFIED),
    )


def placement(x: float, y: float = 0, identity: str = "p", **kwargs) -> Placement:  # noqa: ANN003
    return Placement(
        identity,
        1,
        PlantingType.TREE,
        TREE,
        x,
        y,
        Verdict.ALLOWED,
        (RuleCheck("r", CheckOutcome.PASS, 2, 999),),
        **kwargs,
    )


def verify(points, features=(), rules=(), params=PARAMS):  # noqa: ANN001, ANN201
    return validate_plan(
        Plan(tuple(points), ()), features, (), RuleBook({}, tuple(rules), "test"), params
    )


def test_cached_pass_cannot_hide_a_distance_violation() -> None:
    result = verify([placement(2.1)], [pipe(0, 1)], [rule()])
    assert not result.ok
    issue = next(i for i in result.issues if i.code == "distance")
    assert issue.measured_m == pytest.approx(1.6)


def test_actual_species_crown_is_checked_in_single_species_mode() -> None:
    p = replace(placement(3), species=replace(TREE, crown_mature_m=9))
    r = replace(
        rule(), citation=Citation("test", "табл. 9.1", "Synthetic", CitationStatus.UNVERIFIED)
    )
    result = verify([p], [pipe(0, 0)], [r])
    assert any(i.required_m == 4 for i in result.issues)


def test_species_specific_rule_does_not_need_a_prior_generator_check() -> None:
    p = replace(placement(1), checks=())
    r = replace(rule(), genera=frozenset({"testus"}))
    assert any(i.code == "distance" for i in verify([p], [pipe(0, 0)], [r]).issues)


def test_barrier_must_be_documented_when_it_is_required() -> None:
    params = replace(PARAMS, root_barriers=True)
    result = verify([placement(1)], [pipe(0, 0)], [rule()], params)
    assert any(i.code == "barrier_not_documented" for i in result.issues)
    assert verify(
        [placement(1, notes=("посадка с прикорневым барьером",))], [pipe(0, 0)], [rule()], params
    ).ok


def test_unmarked_approval_is_not_allowed() -> None:
    rules = [rule(severity=Severity.NEEDS_APPROVAL)]
    assert not verify([placement(1)], [pipe(0, 0)], rules).ok
    assert verify([replace(placement(1), verdict=Verdict.NEEDS_APPROVAL)], [pipe(0, 0)], rules).ok


def test_duplicate_nan_and_overlapping_placements_are_detected() -> None:
    result = verify(
        [
            placement(10, identity="same"),
            placement(11, identity="same"),
            placement(float("nan"), identity="nan"),
        ]
    )
    assert {"duplicate_id", "nonfinite_coordinate", "spacing"} <= {i.code for i in result.issues}


def test_tree_and_shrub_footprints_cannot_overlap() -> None:
    shrub = replace(
        placement(10.5, identity="shrub"),
        planting_type=PlantingType.SHRUB,
        species=replace(TREE, code="shrub", life_form=LifeForm.SHRUB_LOW),
    )
    params = replace(PARAMS, planting_radius_m=1.6, shrub_planting_radius_m=0.5)
    assert any(i.code == "spacing" for i in verify([placement(10), shrub], params=params).issues)


def test_quota_is_recomputed_instead_of_trusting_a_stale_summary() -> None:
    points = [placement(i * 10, identity=str(i)) for i in range(10)]
    assert any(
        i.code == "quota"
        for i in verify(points, params=replace(PARAMS, assortment_mode="auto")).issues
    )


def test_soft_quotas_are_a_penalty_not_a_violation() -> None:
    """notes/34: при мягких квотах перебор доли вида - штраф подбора и индекса, план проходит."""
    points = [placement(i * 10, identity=str(i)) for i in range(10)]
    soft = replace(PARAMS, assortment_mode="auto", quota_penalty=5.0)
    assert not any(i.code == "quota" for i in verify(points, params=soft).issues)
    assert trim_to_quotas(points, soft, (TREE,), {}, removable=lambda _: True) == tuple(points)


def test_conifer_ceiling_stays_hard_with_soft_quotas() -> None:
    pine = replace(TREE, code="pine", genus="pinus", family="Pinaceae", name_lat="Pinus s")
    points = [
        replace(placement(i * 10, identity=str(i)), species=pine if i < 8 else TREE)
        for i in range(10)
    ]
    soft = replace(PARAMS, assortment_mode="auto", quota_penalty=5.0, conifer_share=(0.0, 0.5))
    issues = [i for i in verify(points, params=soft).issues if i.code == "quota"]
    assert issues
    assert all("is_conifer" in issue.message for issue in issues)


def test_tree_step_never_drops_below_the_743pp_minimum() -> None:
    """743-ПП, табл. 3.6.2: деревья не ближе 5 м; допуск 5% не опускает шаг 5 м до 4,75 м."""
    params = replace(PARAMS, spacing_m=5.0)
    close = [placement(0, identity="a"), placement(4.9, identity="b")]
    assert any(i.code == "spacing" for i in verify(close, params=params).issues)
    exact = [placement(0, identity="a"), placement(5.0, identity="b")]
    assert not any(i.code == "spacing" for i in verify(exact, params=params).issues)
    assert step_with_tolerance(6.0, PlantingType.TREE) == pytest.approx(5.7)
    assert step_with_tolerance(5.0, PlantingType.TREE) == pytest.approx(5.0)
    assert step_with_tolerance(1.0, PlantingType.SHRUB) == pytest.approx(0.95)


def test_trim_removes_only_stage_additions_until_quotas_hold() -> None:
    """Добавочные этапы кустарника подбирают вид в своей выборке; квота - по всему плану.
    Обрезка снимает только разрешённые посадки и ровно до выполнения квот."""
    kinds = [
        replace(TREE, code=f"s{i}", genus=f"g{i}", family=f"f{i}", name_lat=f"G{i} s")
        for i in range(10)
    ]
    # Основа разнообразна и сама квоты держит; этап добавил пять посадок одного вида.
    base = [
        replace(placement(i * 10, identity=f"base-{i}"), species=kind)
        for i, kind in enumerate(kinds)
    ]
    extra = [
        replace(placement(200 + i * 10, identity=f"stage-{i}"), species=kinds[0]) for i in range(5)
    ]
    params = replace(PARAMS, assortment_mode="auto")
    assert not any(i.code == "quota" for i in verify(base, params=params).issues)
    assert any(i.code == "quota" for i in verify([*base, *extra], params=params).issues)

    kept = trim_to_quotas(
        (*base, *extra), params, kinds, {}, removable=lambda p: p.placement_id.startswith("st")
    )

    assert [p.placement_id for p in kept[: len(base)]] == [p.placement_id for p in base]
    assert not any(i.code == "quota" for i in verify(kept, params=params).issues)
    assert len(kept) < len(base) + len(extra)


def test_trim_leaves_the_plan_alone_when_nothing_may_be_removed() -> None:
    points = tuple(placement(i * 10, identity=str(i)) for i in range(10))
    params = replace(PARAMS, assortment_mode="auto")

    assert trim_to_quotas(points, params, (TREE,), {}, removable=lambda _: False) == points


def test_site_conditions_are_checked_after_a_manual_species_change() -> None:
    p = replace(placement(1), species=replace(TREE, hardiness_zone=8, salt_tolerance=0))
    curb = replace(pipe(0, 0), object_class=ObjectClass.CURB)
    assert {"hardiness", "salt"} <= {issue.code for issue in verify([p], [curb]).issues}


def test_approval_under_a_line_does_not_bypass_height_limit() -> None:
    p = replace(placement(1), verdict=Verdict.NEEDS_APPROVAL, species=replace(TREE, height_m=10))
    overhead = replace(pipe(0, 0), object_class=ObjectClass.POWER_LINE_OVERHEAD)
    r = replace(
        rule(severity=Severity.NEEDS_APPROVAL), object_class=ObjectClass.POWER_LINE_OVERHEAD
    )
    assert any(i.code == "overhead_height" for i in verify([p], [overhead], [r]).issues)


def test_single_species_generation_passes_the_actual_crown_certificate(tmp_path: Path) -> None:
    source = tmp_path / "single.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"assortment_mode": "single"})
    report = container.use_case.execute(
        PlanRequest("single", source, tmp_path / "out", "strict", params)
    )
    assert report.plan.placements
    assert report.validation is not None
    assert report.validation.ok
    assert all(p.species.code == "tilia_cordata" for p in report.plan.placements)


@pytest.mark.parametrize("seed", range(10))
def test_distance_certificate_agrees_with_exhaustive_wall_oracle(seed: int) -> None:
    rng = np.random.default_rng(seed)
    features = [
        pipe(float(x), float(d), i)
        for i, (x, d) in enumerate(
            zip(rng.uniform(-10, 10, 15), rng.uniform(0, 8, 15), strict=True)
        )
    ]
    points = [placement(float(x), identity=str(i)) for i, x in enumerate(rng.uniform(-15, 15, 60))]
    result = verify(points, features, [rule()])
    actual = {i.placements[0] for i in result.issues if i.code == "distance"}
    expected = {
        p.placement_id
        for p in points
        if min(max(0, abs(p.x - f.geometry.coords[0][0]) - f.diameter_m / 2) for f in features)
        + 1e-3
        < 2
    }
    assert actual == expected
