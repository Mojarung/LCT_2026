"""Bounded maximum-weight selection with checked incumbents and explicit bounds.

Binary x[i]; conflicting pairs and station alternatives may sum to at most one.
No dense distance matrix. The caller supplies the existing greedy incumbent so
neither a timeout nor a broken solver result can silently worsen that objective.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_array
from scipy.spatial import KDTree

from green.domain.selection import SelectionReport

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from scipy.optimize import OptimizeResult

_INTEGER_TOL = 1e-6
_MAX_WEIGHT_SUM = 1_000_000_000_000
_XY_DIMENSIONS = 2
_BINARY_CUTOFF = 0.5


@dataclass(frozen=True, slots=True)
class SelectionProblem:
    xy: tuple[tuple[float, float], ...]
    weights: tuple[int, ...]
    stations: tuple[str, ...]
    min_gap_m: float
    objective_description: str = "Maximum sum of positive integer candidate weights"

    def validate(self) -> None:
        if not (len(self.xy) == len(self.weights) == len(self.stations)):
            raise ValueError("Candidate coordinates, weights and stations must have equal lengths")
        if not math.isfinite(self.min_gap_m) or self.min_gap_m <= 0:
            raise ValueError("Candidate spacing must be finite and positive")
        if any(len(p) != _XY_DIMENSIONS or not all(math.isfinite(v) for v in p) for p in self.xy):
            raise ValueError("Candidate coordinates must be finite two-dimensional points")
        if any(type(w) is not int or w <= 0 for w in self.weights):
            raise ValueError("Candidate weights must be positive integers")
        if sum(self.weights) > _MAX_WEIGHT_SUM:
            raise ValueError("Candidate weight sum exceeds the numerical precision budget")

    def feasible(self, selected: Sequence[int]) -> bool:
        """Independent check in coordinates, without trusting the MILP constraint matrix."""
        if len(set(selected)) != len(selected):
            return False
        if any(i < 0 or i >= len(self.xy) for i in selected):
            return False
        if len({self.stations[i] for i in selected}) != len(selected):
            return False
        cells: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
        for i in selected:
            x, y = self.xy[i]
            cx, cy = math.floor(x / self.min_gap_m), math.floor(y / self.min_gap_m)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if any(
                        math.hypot(x - px, y - py) < self.min_gap_m
                        for px, py in cells.get((cx + dx, cy + dy), ())
                    ):
                        return False
            cells[cx, cy].append((x, y))
        return True

    def objective(self, selected: Sequence[int]) -> int:
        return sum(self.weights[i] for i in selected)

    def upper_bound(self) -> int:
        # A valid bound even when spatial conflicts cannot be built within the limit.
        best: dict[str, int] = {}
        for station, weight in zip(self.stations, self.weights, strict=True):
            best[station] = max(best.get(station, 0), weight)
        return sum(best.values())


def select_candidates(
    problem: SelectionProblem,
    baseline: Sequence[int],
    *,
    time_limit_s: float = 5.0,
    max_candidates: int = 6000,
    max_conflicts: int = 200_000,
) -> SelectionReport:
    started = time.perf_counter()
    problem.validate()
    if not math.isfinite(time_limit_s) or time_limit_s <= 0:
        raise ValueError("Solver time limit must be finite and positive")
    if not problem.feasible(baseline):
        raise ValueError("The supplied baseline violates candidate constraints")
    chosen = tuple(sorted(baseline))
    upper = float(problem.upper_bound())
    status, optimal, conflicts = "candidate_limit", False, None
    if not problem.xy:
        status, optimal = "empty", True
    elif len(problem.xy) <= max_candidates:
        pairs = _conflicts(problem, max_conflicts)
        if pairs is None:
            status = "conflict_limit"
        else:
            conflicts = len(pairs)
            chosen, upper, status, optimal = _solve(problem, chosen, pairs, time_limit_s)
    objective = problem.objective(chosen)
    digest = hashlib.sha256(
        json.dumps(
            [problem.xy, problem.weights, problem.stations, problem.min_gap_m],
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    return SelectionReport(
        candidate_sha256=digest,
        candidates=len(problem.xy),
        selected=chosen,
        baseline_count=len(baseline),
        baseline_objective=problem.objective(baseline),
        objective=objective,
        upper_bound=upper,
        relative_gap=max(0.0, upper - objective) / max(1, objective),
        solver_status=status,
        optimal=optimal,
        conflicts=conflicts,
        elapsed_s=round(time.perf_counter() - started, 6),
        objective_description=problem.objective_description,
    )


def _conflicts(problem: SelectionProblem, limit: int) -> NDArray[np.int64] | None:
    xy = np.asarray(problem.xy, dtype=float)
    tree = KDTree(xy)
    # Count before allocating a potentially quadratic pair array (coincident points).
    count = int(tree.count_neighbors(tree, problem.min_gap_m)) - len(xy)
    if count // 2 > limit:
        return None
    pairs = tree.query_pairs(problem.min_gap_m, output_type="ndarray")
    if not len(pairs):
        return pairs
    delta = xy[pairs[:, 0]] - xy[pairs[:, 1]]
    return pairs[np.hypot(delta[:, 0], delta[:, 1]) < problem.min_gap_m]


def _constraints(problem: SelectionProblem, pairs: NDArray[np.int64]) -> LinearConstraint:
    rows = np.repeat(np.arange(len(pairs)), 2).tolist()
    cols = pairs.ravel().tolist()
    groups: dict[str, list[int]] = defaultdict(list)
    for i, station in enumerate(problem.stations):
        groups[station].append(i)
    row = len(pairs)
    for group in groups.values():
        if len(group) > 1:
            rows.extend([row] * len(group))
            cols.extend(group)
            row += 1
    matrix = coo_array(
        (np.ones(len(cols)), (np.asarray(rows, dtype=int), np.asarray(cols, dtype=int))),
        shape=(row, len(problem.xy)),
    ).tocsc()
    return LinearConstraint(matrix, -np.inf, np.ones(row))


def _incumbent(  # noqa: PLR0911 - explicit rejection of each broken solver contract
    problem: SelectionProblem, result: OptimizeResult
) -> tuple[int, ...] | None:
    if result.x is None:
        return None
    vector = np.asarray(result.x)
    if vector.shape != (len(problem.xy),) or not np.isfinite(vector).all():
        return None
    if np.any(np.abs(vector - np.rint(vector)) > _INTEGER_TOL):
        return None
    if np.any(vector < -_INTEGER_TOL) or np.any(vector > 1 + _INTEGER_TOL):
        return None
    selected = tuple(np.flatnonzero(vector > _BINARY_CUTOFF).tolist())
    if not problem.feasible(selected):
        return None
    fun = getattr(result, "fun", None)
    if fun is None or not math.isfinite(fun):
        return None
    if abs(-fun - problem.objective(selected)) > _INTEGER_TOL:
        return None
    return selected


def _solve(
    problem: SelectionProblem,
    baseline: tuple[int, ...],
    pairs: NDArray[np.int64],
    time_limit_s: float,
) -> tuple[tuple[int, ...], float, str, bool]:
    structural_bound = float(problem.upper_bound())
    try:
        result = milp(
            -np.asarray(problem.weights, dtype=float),
            integrality=np.ones(len(problem.xy)),
            bounds=Bounds(0, 1),
            constraints=_constraints(problem, pairs),
            options={"time_limit": time_limit_s, "mip_rel_gap": 0.0},
        )
    except (ValueError, RuntimeError) as error:
        return baseline, structural_bound, f"solver_error:{type(error).__name__}", False
    if result.status not in {0, 1}:
        return baseline, structural_bound, f"solver_status:{result.status}", False
    incumbent = _incumbent(problem, result)
    if result.x is not None and incumbent is None:
        return baseline, structural_bound, "invalid_incumbent", False
    chosen = baseline
    if incumbent is not None and problem.objective(incumbent) > problem.objective(baseline):
        chosen = incumbent
    objective = problem.objective(chosen)
    dual = getattr(result, "mip_dual_bound", None)
    if dual is None or not math.isfinite(dual):
        return chosen, structural_bound, "no_solver_bound", False
    upper = -float(dual)
    if upper + _INTEGER_TOL < objective:
        return chosen, structural_bound, "invalid_solver_bound", False
    upper = min(structural_bound, max(float(objective), upper))
    optimal = result.status == 0 and incumbent is not None and upper - objective <= _INTEGER_TOL
    status = "optimal" if optimal else "limit" if result.status == 1 else "unclosed_bound"
    return chosen, upper, status, optimal
