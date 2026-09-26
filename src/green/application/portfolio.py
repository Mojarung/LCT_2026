"""Keep the baseline and compare fully assembled plans, never just candidate counts."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np

from green.application.constraints import work_boundary
from green.application.errors import InputError
from green.application.quality.site import curb_segments
from green.application.zones import CAPACITY_STAT, SITE_CAPACITY_STAT
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
    score: Callable[[Plan, PlanParams], Plan] | None = None,
) -> tuple[Plan, PlanValidation]:
    """Лучший из проверенных вариантов по индексу качества.

    score оценивает собранный план; он вызывается, когда собраны все варианты: вместимость
    участка (цель плотности индекса) у всех вариантов общая - наибольшая из посчитанных, и
    варианты сравниваются при одной цели. Без score план берётся с той оценкой, что дала сборка.
    """
    if params.placement_solver != "portfolio":
        plan, validation = build(params)
        if validation.ok and score is not None:
            plan = score(_with_site_capacity(plan, (plan,)), params)
        return plan, validation
    outcomes = _build_all(build, params, features)
    built = tuple(outcome[0] for _, _, outcome in outcomes if not isinstance(outcome, str))
    results = []
    best: tuple[Plan, PlanValidation] | None = None
    best_key = (-math.inf, -math.inf)
    chosen = ""
    for name, variant, outcome in outcomes:
        if isinstance(outcome, str):
            results.append(_failed(name, variant, outcome))
            continue
        plan, validation = outcome
        if score is not None:
            plan = score(_with_site_capacity(plan, built), variant)
        index = plan.quality.index if plan.quality else None
        if index is not None and not math.isfinite(index):
            results.append(_failed(name, variant, "Non-finite quality index"))
            continue
        results.append(_succeeded(name, variant, plan))
        key = (index if index is not None else -1.0, -plan.approval_count)
        if best is None or key > best_key:
            best, best_key, chosen = (plan, validation), key, name
    if best is None:
        raise InputError(
            "Нет проверенного варианта посадки: "
            + "; ".join(f"{r.name}: {r.error}" for r in results)
        )
    plan, validation = best
    return replace(plan, portfolio=PortfolioReport(chosen, tuple(results))), validation


def _with_site_capacity(plan: Plan, plans: Sequence[Plan]) -> Plan:
    """План с вместимостью участка: наибольшей из посчитанных вариантами (zones.pack_count)."""
    values = [p.stats[CAPACITY_STAT] for p in plans if CAPACITY_STAT in p.stats]
    if not values:
        return plan
    return replace(plan, stats={**plan.stats, SITE_CAPACITY_STAT: max(values)})


def _build_all(
    build: Callable[[PlanParams], tuple[Plan, PlanValidation]],
    params: PlanParams,
    features: Sequence[Feature],
) -> list[tuple[str, PlanParams, tuple[Plan, PlanValidation] | str]]:
    """Все варианты по порядку: собранный и проверенный план или причина отказа."""
    outcomes: list[tuple[str, PlanParams, tuple[Plan, PlanValidation] | str]] = []
    started = time.perf_counter()
    slowest = 0.0
    budget = params.portfolio_budget_s
    for name, variant in _prioritized(_variants(params, features)):
        # Бюджет времени: следующий вариант не начинается, если самый долгий из посчитанных
        # в него уже не укладывается. Исходный вариант считается всегда (ТЗ: лимит стенда -
        # 30 минут на подбор мест, docs/notes/15).
        elapsed = time.perf_counter() - started
        if budget > 0 and outcomes and elapsed + slowest > budget:
            outcomes.append(
                (
                    name,
                    variant,
                    f"не посчитан: бюджет портфеля {budget:.0f} с, прошло {elapsed:.0f} с",
                )
            )
            continue
        clock = time.perf_counter()
        try:
            plan, validation = build(variant)
        except InputError as error:
            outcomes.append((name, variant, str(error)))
            continue
        finally:
            slowest = max(slowest, time.perf_counter() - clock)
        if not validation.ok:
            message = "; ".join(issue.message for issue in validation.issues[:8])
            outcomes.append((name, variant, message))
            continue
        outcomes.append((name, variant, (plan, validation)))
    return outcomes


def _succeeded(name: str, params: PlanParams, plan: Plan) -> VariantResult:
    return VariantResult(
        name=name,
        solver=params.placement_solver,
        lawn_phase=params.lawn_phase,
        lawn_rotation_deg=params.lawn_rotation_deg,
        lawn_anchor=params.lawn_anchor,
        valid=True,
        quality_index=plan.quality.index if plan.quality else None,
        trees=sum(p.species.is_tree for p in plan.placements),
        shrubs=sum(p.species.is_shrub for p in plan.placements),
        needs_approval=plan.approval_count,
        terms={t.key: t.score for t in plan.quality.terms} if plan.quality else {},
    )


def _failed(name: str, params: PlanParams, error: str) -> VariantResult:
    return VariantResult(
        name=name,
        solver=params.placement_solver,
        lawn_phase=params.lawn_phase,
        lawn_rotation_deg=params.lawn_rotation_deg,
        lawn_anchor=params.lawn_anchor,
        valid=False,
        quality_index=None,
        trees=0,
        shrubs=0,
        needs_approval=0,
        error=error,
    )


# Порядок счёта: исходный вариант, затем объединённый отбор MILP (он чаще выигрывает: больше
# мест при тех же нормах), затем сдвиги и повороты сетки газона. При бюджете времени первыми
# идут самые ценные; при равном индексе выигрывает посчитанный раньше.
_PRIORITY = (
    "baseline",
    "joint",
    "soil_frame_joint",
    "aligned_joint",
    "soil_frame",
    "aligned",
    "phase_x",
    "phase_xy",
)


def _prioritized(variants: list[tuple[str, PlanParams]]) -> list[tuple[str, PlanParams]]:
    rank = {name: position for position, name in enumerate(_PRIORITY)}
    return sorted(variants, key=lambda item: rank.get(item[0], len(rank)))


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
    if params.lawn_anchor != "soil":
        framed = replace(
            base,
            lawn_anchor="soil",
            lawn_rotation_deg=angle if angle is not None else params.lawn_rotation_deg,
        )
        variants.extend(
            (("soil_frame", framed), ("soil_frame_joint", replace(framed, placement_solver="milp")))
        )
    return variants


def _curb_angle(features: Sequence[Feature]) -> float | None:
    # The same unique, clipped linework used for quality: distant annotations and
    # a curb's continuation outside the work site must not choose the local axis.
    segments = curb_segments(features, work_boundary(features))
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
