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
    assert plan.portfolio is not None
    assert plan.quality is not None
    assert plan.portfolio.chosen == winner
    assert plan.quality.index == max(baseline, joint)
    assert len(plan.portfolio.variants) == 2


def test_high_quality_invalid_variant_cannot_win() -> None:
    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        if params.placement_solver == "milp":
            return _plan(0.99), PlanValidation(1, (ValidationIssue("distance", (), "unsafe"),))
        return _plan(0.3), PlanValidation(0, ())

    plan, _ = choose_plan(build, PlanParams(modes=("alley",), placement_solver="portfolio"), ())
    assert plan.portfolio is not None
    assert plan.portfolio.chosen == "baseline"
    assert not plan.portfolio.variants[1].valid
    assert plan.portfolio.variants[1].error == "unsafe"


def test_nonfinite_quality_is_not_selected() -> None:
    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        return _plan(math.nan if params.placement_solver == "milp" else 0.3), PlanValidation(0, ())

    plan, _ = choose_plan(build, PlanParams(modes=("alley",), placement_solver="portfolio"), ())
    assert plan.portfolio is not None
    assert plan.portfolio.chosen == "baseline"
    assert not plan.portfolio.variants[1].valid


def test_incomplete_variant_does_not_discard_valid_baseline() -> None:
    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        if params.placement_solver == "milp":
            raise InputError("No compatible species")
        return _plan(0.3), PlanValidation(0, ())

    plan, _ = choose_plan(build, PlanParams(modes=("alley",), placement_solver="portfolio"), ())
    assert plan.portfolio is not None
    assert plan.portfolio.chosen == "baseline"
    assert plan.portfolio.variants[1].error == "No compatible species"


def test_rejected_variant_reason_groups_repeated_messages() -> None:
    """Реестр Понтрягина: одна и та же фраза восемь раз подряд без посадок. Теперь фраза
    один раз, число посадок и до двух примеров."""
    same = tuple(ValidationIssue("footprint", (f"p-{i}",), "Место не на грунте") for i in range(8))
    other = tuple(
        ValidationIssue("distance", (identity,), "Отступ меньше нормы", "R", 1.0, 2.0)
        for identity in ("q-1", "q-2")
    )

    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        if params.placement_solver == "milp":
            return _plan(0.9), PlanValidation(10, same + other)
        return _plan(0.3), PlanValidation(0, ())

    plan, _ = choose_plan(build, PlanParams(modes=("alley",), placement_solver="portfolio"), ())

    assert plan.portfolio is not None
    assert plan.portfolio.variants[1].error == (
        "Место не на грунте: 8 посадок, например p-0, p-1;"
        " Отступ меньше нормы: 2 посадки (q-1, q-2)"
    )


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
    # Сдвиг фаз на полшага от заданных профилем: вариант phase_xy (порядок - по ценности).
    assert any(phase == pytest.approx((0.2, 0.8)) for phase, _ in visited)
    assert plan.portfolio is not None
    assert plan.portfolio.chosen == "baseline"


def test_soil_frame_is_additional_and_cannot_replace_a_better_baseline() -> None:
    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        return _plan(0.1 if params.lawn_anchor == "soil" else 0.8), PlanValidation(0, ())

    plan, _ = choose_plan(build, PlanParams(placement_solver="portfolio"), ())
    assert plan.portfolio is not None
    assert plan.portfolio.chosen == "baseline"
    # Порядок счёта - по ценности: исходный, объединённый отбор, затем сдвиги сетки.
    assert [v.name for v in plan.portfolio.variants] == [
        "baseline",
        "joint",
        "joint_lawn_6",
        "joint_lawn_7",
        "soil_frame_joint",
        "soil_frame",
        "phase_x",
        "phase_xy",
    ]
    soil = [v for v in plan.portfolio.variants if v.name.startswith("soil_frame")]
    assert all(v.lawn_anchor == "soil" for v in soil)


def test_budget_keeps_the_baseline_and_skips_what_would_not_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Лимит стенда - 30 минут на подбор мест (docs/notes/15): варианты сверх бюджета не
    начинаются, исходный считается всегда, пропуск назван в отчёте портфеля."""
    clock = [0.0]
    monkeypatch.setattr("green.application.portfolio.time.perf_counter", lambda: clock[0])

    def build(params: PlanParams) -> tuple[Plan, PlanValidation]:
        clock[0] += 6.0  # каждый вариант - 6 секунд
        return _plan(0.9 if params.placement_solver == "milp" else 0.5), PlanValidation(0, ())

    params = PlanParams(modes=("alley",), placement_solver="portfolio", portfolio_budget_s=10.0)
    plan, validation = choose_plan(build, params, ())
    assert validation.ok
    assert plan.portfolio is not None
    assert plan.portfolio.chosen == "baseline"
    joint = next(v for v in plan.portfolio.variants if v.name == "joint")
    assert not joint.valid
    assert "бюджет портфеля" in joint.error
