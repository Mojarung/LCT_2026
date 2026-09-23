from __future__ import annotations

import math

import pytest

from green.application.errors import InputError
from green.application.params import PlanParams
from green.application.portfolio import choose_plan
from green.application.validation import PlanValidation, ValidationIssue
from green.domain.planting import Plan
from green.domain.quality import PlanQuality


def _plan(score: float | None) -> Plan:
    return Plan((), (), quality=PlanQuality(score, "", (), 0, {}, ()))


@pytest.mark.parametrize(
    ("baseline", "joint", "winner"),
    [(0.7, 0.5, "baseline"), (0.5, 0.7, "joint"), (0.5, 0.5, "baseline")],
)
def test_compare_complete_quality_and_keep_baseline_on_ties(
    baseline: float,
    joint: float,
    winner: str,
) -> None:
    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        return _plan(baseline if params.placement_solver == "greedy" else joint), PlanValidation(
            0, ()
        )

    plan, validation = choose_plan(
        build, PlanParams(modes=("alley",), placement_solver="portfolio"), ()
    )
    assert validation.ok
    assert plan.portfolio.chosen == winner
    assert plan.quality.index == max(baseline, joint)
    assert len(plan.portfolio.variants) == 2


def test_high_quality_invalid_variant_cannot_win() -> None:
    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        if params.placement_solver == "milp":
            return _plan(0.99), PlanValidation(1, (ValidationIssue("distance", (), "unsafe"),))
        return _plan(0.3), PlanValidation(0, ())

    plan, _ = choose_plan(build, PlanParams(modes=("alley",), placement_solver="portfolio"), ())
    assert plan.portfolio.chosen == "baseline"
    assert not plan.portfolio.variants[1].valid
    assert plan.portfolio.variants[1].error == "unsafe"


def test_nonfinite_quality_is_not_selected() -> None:
    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        return _plan(math.nan if params.placement_solver == "milp" else 0.3), PlanValidation(0, ())

    plan, _ = choose_plan(build, PlanParams(modes=("alley",), placement_solver="portfolio"), ())
    assert plan.portfolio.chosen == "baseline"
    assert not plan.portfolio.variants[1].valid


def test_incomplete_variant_does_not_discard_valid_baseline() -> None:
    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        if params.placement_solver == "milp":
            raise InputError("No compatible species")
        return _plan(0.3), PlanValidation(0, ())

    plan, _ = choose_plan(build, PlanParams(modes=("alley",), placement_solver="portfolio"), ())
    assert plan.portfolio.chosen == "baseline"
    assert plan.portfolio.variants[1].error == "No compatible species"


def test_all_invalid_variants_stop_generation() -> None:
    def build(_params: PlanParams) -> tuple[Plan, PlanValidation]:
        return _plan(1.0), PlanValidation(1, (ValidationIssue("distance", (), "unsafe"),))

    with pytest.raises(InputError, match="Нет проверенного варианта"):
        choose_plan(build, PlanParams(modes=("alley",), placement_solver="portfolio"), ())


def test_configured_phases_are_preserved_in_baseline() -> None:
    visited = []

    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        visited.append((params.lawn_phase, params.lawn_rotation_deg))
        return _plan(0.3), PlanValidation(0, ())

    params = PlanParams(placement_solver="portfolio", lawn_phase=(0.7, 0.3), lawn_rotation_deg=30)
    plan, _ = choose_plan(build, params, ())
    assert visited[0] == ((0.7, 0.3), 30)
    assert visited[-1][0] == pytest.approx((0.2, 0.8))
    assert plan.portfolio.chosen == "baseline"
