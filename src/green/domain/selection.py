"""Evidence about one finite candidate problem, before species assignment."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SelectionReport:
    candidate_sha256: str
    candidates: int
    selected: tuple[int, ...]
    baseline_count: int
    baseline_objective: int
    objective: int
    upper_bound: float
    relative_gap: float
    solver_status: str
    optimal: bool
    conflicts: int | None
    elapsed_s: float
    objective_description: str
    scope: str = (
        "Finite eligible candidates, pair spacing and one candidate per station; "
        "before species assignment, quotas, shrub substitution and manual edits. "
        "Optimal means the numerical MILP bound closes, not a continuous or aesthetic optimum."
    )
