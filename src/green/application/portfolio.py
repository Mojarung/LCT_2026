"""Keep the baseline and compare fully assembled plans, never just candidate counts."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from green.application.errors import InputError
from green.application.quality.site import site_of
from green.domain.portfolio import PortfolioReport, VariantResult

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from green.application.params import PlanParams
    from green.application.validation import PlanValidation
    from green.domain.objects import Feature
    from green.domain.planting import Plan

_AXIS_ANGLE_EPS_DEG = 1e-6


def choose_plan(
    build: Callable[[PlanParams], tuple[Plan, PlanValidation]],
    params: PlanParams,
    features: Sequence[Feature],
) -> tuple[Plan, PlanValidation]:
    if params.placement_solver != "portfolio":
        return build(params)
    results = []
    best: tuple[Plan, PlanValidation] | None = None
    best_key = (-math.inf, -math.inf)
    chosen = ""
    for name, variant in _variants(params, features):
        try:
            plan, validation = build(variant)
        except InputError as error:
            results.append(_failed(name, variant, str(error)))
            continue
        if not validation.ok:
            message = "; ".join(issue.message for issue in validation.issues[:8])
            results.append(_failed(name, variant, message))
            continue
        score = plan.quality.index if plan.quality else None
        if score is not None and not math.isfinite(score):
            results.append(_failed(name, variant, "Non-finite quality index"))
            continue
        results.append(
            VariantResult(
                name=name,
                solver=variant.placement_solver,
                lawn_phase=variant.lawn_phase,
                lawn_rotation_deg=variant.lawn_rotation_deg,
                valid=True,
                quality_index=score,
                trees=sum(p.species.is_tree for p in plan.placements),
                shrubs=sum(p.species.is_shrub for p in plan.placements),
                needs_approval=plan.approval_count,
            )
        )
        key = (score if score is not None else -1.0, -plan.approval_count)
        if best is None or key > best_key:
            best, best_key, chosen = (plan, validation), key, name
    if best is None:
        raise InputError(
            "Нет проверенного варианта посадки: "
            + "; ".join(f"{r.name}: {r.error}" for r in results)
        )
    plan, validation = best
    return replace(plan, portfolio=PortfolioReport(chosen, tuple(results))), validation


def _failed(name: str, params: PlanParams, error: str) -> VariantResult:
    return VariantResult(
        name=name,
        solver=params.placement_solver,
        lawn_phase=params.lawn_phase,
        lawn_rotation_deg=params.lawn_rotation_deg,
        valid=False,
        quality_index=None,
        trees=0,
        shrubs=0,
        needs_approval=0,
        error=error,
    )


def _variants(params: PlanParams, features: Sequence[Feature]) -> list[tuple[str, PlanParams]]:
    base = replace(params, placement_solver="greedy")
    variants = [("baseline", base), ("joint", replace(base, placement_solver="milp"))]
    if "lawn" not in params.modes:
        return variants
    px, py = params.lawn_phase
    variants.extend(
        (
            ("phase_x", replace(base, lawn_phase=((px + 0.5) % 1, py))),
            ("phase_xy", replace(base, lawn_phase=((px + 0.5) % 1, (py + 0.5) % 1))),
        )
    )
    angle = _curb_angle(features)
    if angle is not None and not math.isclose(angle, params.lawn_rotation_deg, abs_tol=1e-6):
        variants.extend(
            (
                ("aligned", replace(base, lawn_rotation_deg=angle)),
                ("aligned_joint", replace(base, lawn_rotation_deg=angle, placement_solver="milp")),
            )
        )
    return variants


def _curb_angle(features: Sequence[Feature]) -> float | None:
    # The same unique, clipped linework used for quality: distant annotations and
    # a curb's continuation outside the work site must not choose the local axis.
    segments = site_of(features).curb_segments
    if not len(segments):
        return None
    # Integrate the axial direction tensor along unique physical linework. Opposite
    # directions reinforce one another; closing/reversing/splitting a line cannot
    # cancel its orientation or give a short, densely segmented side more votes.
    vectors = segments[:, 1] - segments[:, 0]
    lengths = np.linalg.norm(vectors, axis=1)
    vectors, lengths = vectors[lengths > 0], lengths[lengths > 0]
    if not len(lengths):
        return None
    dx, dy = vectors.T
    axial_x = math.fsum(((dx * dx - dy * dy) / lengths).tolist())
    axial_y = math.fsum((2 * dx * dy / lengths).tolist())
    # A square/circle has no dominant axis. This only suppresses numerical noise;
    # the direction is a candidate heuristic and never changes feasibility rules.
    if math.hypot(axial_x, axial_y) <= 1e-8 * math.fsum(lengths.tolist()):
        return None
    angle = (math.degrees(math.atan2(axial_y, axial_x)) / 2) % 180
    return 0.0 if min(angle, 180 - angle) <= _AXIS_ANGLE_EPS_DEG else angle
