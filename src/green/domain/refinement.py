"""Trace of bounded improvement; separate from the original generation certificate."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RefinementAttempt:
    placement_id: str
    before: float
    after: float | None
    predicted_delta: float
    outcome: str
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RefinementReport:
    baseline_index: float | None
    final_index: float | None
    attempts: tuple[RefinementAttempt, ...]
    stop: str
    max_attempts: int
    scope: str = (
        "Bounded single-deletion search from an independently valid complete plan. "
        "Every accepted change passes full validation and increases the configured index. "
        "Defined weighted metrics must remain defined. Individual effects are recomputed. "
        "No guarantee of a global optimum, optimal species changes or expert aesthetics."
    )
