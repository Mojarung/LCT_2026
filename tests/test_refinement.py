"""Improvement must follow actual feasibility and recalculated scores, not a ranking."""

from __future__ import annotations

from dataclasses import replace

import pytest

from green.application.errors import InputError
from green.application.refinement import refine_plan
from green.application.validation import PlanValidation, ValidationIssue
from green.domain.norms import PlantingType
from green.domain.planting import Placement, Plan, Species, Verdict
from green.domain.quality import PlanQuality, PlantingValue, QualityTerm

SPECIES = Species("s", "species", "species", 1)
TERM = QualityTerm("test", "test", 1, 0.5, "test", "test")


def _quality(index: float | None, values: dict[str, float], *, defined: bool = True) -> PlanQuality:
    return PlanQuality(
        index,
        "",
        (TERM if defined else replace(TERM, score=None, weight=0),),
        0,
        {},
        (),
        {key: PlantingValue(key, value, {}) for key, value in values.items()},
    )


def _plan(index: float | None = 0.5) -> Plan:
    plants = tuple(
        Placement(key, i, PlantingType.TREE, SPECIES, i * 6.0, 5.0, Verdict.ALLOWED, ())
        for i, key in enumerate(("a", "b", "c"), 1)
    )
    return Plan(plants, (), quality=_quality(index, {"a": -0.1, "b": -0.05, "c": 0.2}))


def _valid(plan: Plan) -> PlanValidation:
    return PlanValidation(len(plan.placements), ())


def test_higher_score_with_invalid_composition_cannot_replace_baseline() -> None:
    plan = _plan()

    def check(candidate: Plan) -> tuple[Plan, PlanValidation]:
        return replace(candidate, quality=_quality(0.9, {})), PlanValidation(
            len(candidate.placements),
            (ValidationIssue("quota", (), "species share"),),
        )

    selected, valid, report = refine_plan(plan, _valid(plan), check)
    assert selected is plan
    assert valid.ok
    assert len(report.attempts) == 2
    assert all(a.outcome == "invalid" for a in report.attempts)
    assert report.attempts[0].issues == ("quota: species share",)


def test_deltas_are_recomputed_and_nonadditive_deletions_are_not_accepted() -> None:
    plan = _plan()
    visited = []

    def check(candidate: Plan) -> tuple[Plan, PlanValidation]:
        ids = tuple(p.placement_id for p in candidate.placements)
        visited.append(ids)
        score, values = (0.6, {"b": -0.1, "c": 0.2}) if ids == ("b", "c") else (0.4, {})
        return replace(candidate, quality=_quality(score, values)), _valid(candidate)

    selected, _, report = refine_plan(plan, _valid(plan), check)
    assert visited == [("b", "c"), ("c",)]
    assert selected.quality is not None
    assert selected.quality.index == 0.6
    assert [p.placement_id for p in selected.placements] == ["b", "c"]
    assert [p.number for p in selected.placements] == [1, 2]
    assert [p.number for p in plan.placements] == [1, 2, 3]
    assert [a.outcome for a in report.attempts] == ["accepted", "no_gain"]


def test_improvement_cannot_come_from_disappearing_metric() -> None:
    plan = _plan()

    def check(candidate: Plan) -> tuple[Plan, PlanValidation]:
        return replace(candidate, quality=_quality(0.9, {}, defined=False)), _valid(candidate)

    selected, _, report = refine_plan(plan, _valid(plan), check)
    assert selected is plan
    assert all(a.outcome == "lost_metric" for a in report.attempts)


@pytest.mark.parametrize("after", [0.4, 0.5, 0.500001, None, float("nan"), float("inf")])
def test_no_material_finite_gain_preserves_baseline(after: float | None) -> None:
    plan = _plan()

    def check(candidate: Plan) -> tuple[Plan, PlanValidation]:
        return replace(candidate, quality=_quality(after, {})), _valid(candidate)

    selected, _, report = refine_plan(plan, _valid(plan), check)
    assert selected is plan
    assert all(a.outcome == "no_gain" for a in report.attempts)


@pytest.mark.parametrize("budget", [0, 1, 2])
def test_attempt_budget_counts_invalid_proposals(budget: int) -> None:
    plan = _plan()
    visited = []

    def check(candidate: Plan) -> tuple[Plan, PlanValidation]:
        visited.append(candidate)
        return replace(candidate, quality=_quality(0.4, {})), _valid(candidate)

    _, _, report = refine_plan(plan, _valid(plan), check, max_attempts=budget)
    assert len(visited) == budget
    assert report.stop == "attempt_limit"


def test_zero_index_is_a_valid_starting_score() -> None:
    plan = _plan(0.0)

    def check(candidate: Plan) -> tuple[Plan, PlanValidation]:
        return replace(candidate, quality=_quality(0.1, {})), _valid(candidate)

    selected, _, report = refine_plan(plan, _valid(plan), check)
    assert selected.quality is not None
    assert selected.quality.index == 0.1
    assert report.baseline_index == 0


def test_missing_index_and_invalid_baseline_never_call_search() -> None:
    plan = _plan(None)

    def check(_candidate: Plan) -> tuple[Plan, PlanValidation]:
        pytest.fail("search should not run")

    selected, _, report = refine_plan(plan, _valid(plan), check)
    assert selected is plan
    assert report.stop == "no_index"
    invalid = PlanValidation(3, (ValidationIssue("distance", (), "too close"),))
    with pytest.raises(InputError, match="valid starting"):
        refine_plan(plan, invalid, check)
    with pytest.raises(ValueError, match="non-negative"):
        refine_plan(plan, _valid(plan), check, max_attempts=-1)
