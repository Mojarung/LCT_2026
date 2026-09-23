"""Bounded local improvement of a complete plan, with a fresh feasibility gate.

Individual quality deltas only order proposals. The changed plan is evaluated and
validated in full; it is never accepted from the predicted delta alone.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from green.application.errors import InputError
from green.domain.refinement import RefinementAttempt, RefinementReport

if TYPE_CHECKING:
    from collections.abc import Callable

    from green.application.validation import PlanValidation
    from green.domain.planting import Plan
    from green.domain.quality import PlanQuality

GAIN_EPS = 1e-6
PROPOSAL_EPS = 2e-6


def _index(plan: Plan) -> float | None:
    value = plan.quality.index if plan.quality is not None else None
    return value if value is not None and math.isfinite(value) else None


def _defined(quality: PlanQuality) -> set[str]:
    return {term.key for term in quality.terms if term.score is not None and term.weight > 0}


def refine_plan(
    plan: Plan,
    validation: PlanValidation,
    check: Callable[[Plan], tuple[Plan, PlanValidation]],
    *,
    max_attempts: int = 32,
) -> tuple[Plan, PlanValidation, RefinementReport]:
    """Keep the baseline unless a fully checked, strictly better deletion exists."""
    if max_attempts < 0:
        raise ValueError("Refinement attempt budget must be non-negative")
    if not validation.ok:
        raise InputError("Refinement requires an independently valid starting plan")
    baseline = _index(plan)
    if baseline is None or plan.quality is None:
        return plan, validation, RefinementReport(baseline, baseline, (), "no_index", max_attempts)
    required = _defined(plan.quality)
    attempts: list[RefinementAttempt] = []
    current, certificate = plan, validation
    stop = "no_valid_improvement"
    while len(attempts) < max_attempts:
        score = _index(current)
        if score is None or current.quality is None:
            break
        # Stable ties follow the current drawing order, not source-hash spelling.
        identities = {p.placement_id for p in current.placements}
        proposals = sorted(
            (
                value
                for value in current.quality.values.values()
                if value.placement_id in identities and value.delta < -PROPOSAL_EPS
            ),
            key=lambda value: value.delta,
        )
        improved = False
        for value in proposals[: max_attempts - len(attempts)]:
            kept = [p for p in current.placements if p.placement_id != value.placement_id]
            candidate = replace(
                current,
                placements=tuple(replace(p, number=i) for i, p in enumerate(kept, 1)),
                quality=None,
                explanations=(),
            )
            candidate, result = check(candidate)
            after = _index(candidate)
            outcome = _outcome(candidate, result, required, score)
            attempts.append(
                RefinementAttempt(
                    value.placement_id,
                    score,
                    after,
                    value.delta,
                    outcome,
                    tuple(f"{issue.code}: {issue.message}" for issue in result.issues),
                )
            )
            if outcome == "accepted":
                current, certificate = candidate, result
                improved = True
                break
        if not improved:
            break
    if len(attempts) >= max_attempts:
        stop = "attempt_limit"
    report = RefinementReport(baseline, _index(current), tuple(attempts), stop, max_attempts)
    return current, certificate, report


def _outcome(plan: Plan, validation: PlanValidation, required: set[str], before: float) -> str:
    if not validation.ok:
        return "invalid"
    if plan.quality is None or not required <= _defined(plan.quality):
        return "lost_metric"
    after = _index(plan)
    if after is None or after <= before + GAIN_EPS:
        return "no_gain"
    return "accepted"
