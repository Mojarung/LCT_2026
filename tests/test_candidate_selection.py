"""Small exact oracles and adversarial solver outputs, independent of model assembly."""

from __future__ import annotations

import itertools
import math
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import pytest
from scipy.optimize import OptimizeResult

from green.application.candidate_selection import SelectionProblem, select_candidates

if TYPE_CHECKING:
    from collections.abc import Sequence


def _oracle(problem: SelectionProblem) -> int:
    best = 0
    for bits in itertools.product((False, True), repeat=len(problem.xy)):
        chosen = [i for i, bit in enumerate(bits) if bit]
        if any(
            problem.stations[i] == problem.stations[j]
            or math.dist(problem.xy[i], problem.xy[j]) < problem.min_gap_m
            for i, j in itertools.combinations(chosen, 2)
        ):
            continue
        best = max(best, sum(problem.weights[i] for i in chosen))
    return best


def _trap() -> SelectionProblem:
    return SelectionProblem(((0, 0), (-0.9, 0), (0.9, 0)), (1, 1, 1), ("a", "b", "c"), 1)


def test_global_choice_escapes_greedy_trap() -> None:
    report = select_candidates(_trap(), (0,))
    assert report.selected == (1, 2)
    assert report.baseline_objective == 1
    assert report.objective == report.upper_bound == 2
    assert report.optimal
    assert report.relative_gap == 0


@pytest.mark.parametrize("seed", range(18))
def test_milp_matches_all_subsets(seed: int) -> None:
    rng = np.random.default_rng(seed)
    problem = SelectionProblem(
        tuple(map(tuple, rng.uniform(-4, 4, (11, 2)).tolist())),
        tuple(rng.integers(1, 50, 11).tolist()),
        tuple(str(i) for i in rng.integers(0, 8, 11)),
        2.7,
    )
    report = select_candidates(problem, ())
    assert report.objective == _oracle(problem)
    assert report.optimal
    assert report.upper_bound == pytest.approx(report.objective)
    assert problem.feasible(report.selected)


@pytest.mark.parametrize(("scale", "angle"), [(1, 0), (1000, 0.73), (0.3048, -1.2)])
def test_geometry_problem_transfers_between_units_rotation_and_origin(
    scale: float, angle: float
) -> None:
    base = _trap()
    xy = tuple(
        (
            scale * (x * math.cos(angle) - y * math.sin(angle)) + 1_000_000,
            scale * (x * math.sin(angle) + y * math.cos(angle)) - 300_000,
        )
        for x, y in base.xy
    )
    report = select_candidates(replace(base, xy=xy, min_gap_m=base.min_gap_m * scale), (0,))
    assert report.selected == (1, 2)
    assert report.optimal


def test_exact_gap_is_accepted_and_same_station_is_exclusive() -> None:
    problem = SelectionProblem(((0, 0), (1, 0), (50, 0)), (1, 1, 10), ("a", "b", "a"), 1)
    report = select_candidates(problem, (0, 1))
    assert report.selected == (1, 2)
    assert report.objective == 11


@pytest.mark.parametrize(
    ("vector", "fun"),
    [
        ([0.5, 0, 0], -0.5),
        ([1, 1, 1], -3),
        ([2, 0, 0], -2),
        ([float("nan"), 0, 0], -1),
        ([0, 1], -1),
        ([0, 1, 1], -100),
    ],
)
def test_solver_cannot_certify_invalid_incumbent(
    monkeypatch: pytest.MonkeyPatch,
    vector: list[float],
    fun: float,
) -> None:
    result = OptimizeResult(status=0, x=np.array(vector), fun=fun, mip_dual_bound=fun)
    monkeypatch.setattr("green.application.candidate_selection.milp", lambda *_a, **_kw: result)
    report = select_candidates(_trap(), (0,))
    assert report.selected == (0,)
    assert not report.optimal
    assert report.solver_status == "invalid_incumbent"


@pytest.mark.parametrize(("vector", "fun"), [(None, None), ([0, 0, 0], 0), ([0, 1, 1], -2)])
def test_timeout_keeps_best_checked_plan_and_valid_upper_bound(
    monkeypatch: pytest.MonkeyPatch,
    vector: list[float] | None,
    fun: float | None,
) -> None:
    result = OptimizeResult(status=1, x=vector, fun=fun, mip_dual_bound=-2.5)
    monkeypatch.setattr("green.application.candidate_selection.milp", lambda *_a, **_kw: result)
    report = select_candidates(_trap(), (0,))
    assert report.objective >= report.baseline_objective
    assert report.upper_bound == 2.5
    assert not report.optimal
    assert report.solver_status == "limit"


@pytest.mark.parametrize("dual", [None, float("nan"), 5])
def test_invalid_bound_is_not_presented_as_optimal(
    monkeypatch: pytest.MonkeyPatch,
    dual: float | None,
) -> None:
    result = OptimizeResult(status=0, x=[0, 1, 1], fun=-2, mip_dual_bound=dual)
    monkeypatch.setattr("green.application.candidate_selection.milp", lambda *_a, **_kw: result)
    report = select_candidates(_trap(), (0,))
    assert report.selected == (1, 2)
    assert not report.optimal
    assert report.upper_bound == 3  # independently known station bound


def test_limits_apply_before_solver_and_quadratic_graph_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Resource-limited case must not call the MILP solver")

    monkeypatch.setattr("green.application.candidate_selection.milp", fail)
    assert select_candidates(_trap(), (0,), max_candidates=2).solver_status == "candidate_limit"
    dense = SelectionProblem(((0, 0),) * 2000, (1,) * 2000, ("a",) * 2000, 1)
    report = select_candidates(dense, (0,), max_conflicts=100)
    assert report.solver_status == "conflict_limit"
    assert report.selected == (0,)
    assert report.conflicts is None


def test_empty_problem() -> None:
    report = select_candidates(SelectionProblem((), (), (), 1), ())
    assert report.optimal
    assert report.objective == report.upper_bound == 0


@pytest.mark.parametrize("baseline", [(0, 1), (0, 0), (10,), (-1,)])
def test_invalid_baseline_is_an_error(baseline: Sequence[int]) -> None:
    with pytest.raises(ValueError, match="baseline"):
        select_candidates(_trap(), baseline)


@pytest.mark.parametrize(
    "changes",
    [
        {"weights": (1, 1)},
        {"weights": (0, 1, 1)},
        {"weights": (1.2, 1, 1)},
        {"min_gap_m": float("nan")},
        {"xy": ((float("inf"), 0), (0, 0), (1, 1))},
    ],
)
def test_invalid_problem_is_an_error(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="Candidate"):
        select_candidates(replace(_trap(), **changes), ())
