"""Правка плана на карте: проверка точки, применение правок, пересборка DXF.

Правки копятся в памяти прогона и попадают в файлы только по явной команде: перезапись DXF
и сверка целостности на Берзарина занимают десятки секунд, и делать это на каждое
перетаскивание нельзя.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, BackgroundTasks, Response

from green.application.editing import Edit, EditKind, apply_edits, check_point
from green.infrastructure.reports.artifacts import plan_payload, quality_payload
from green.interfaces.api.dependencies import ContainerDep
from green.interfaces.api.errors import PROBLEM_RESPONSES, EditContextLostError, conflict_response
from green.interfaces.api.schemas import (
    CheckIn,
    CheckOut,
    DraftOut,
    EditsIn,
    PlanSummaryOut,
    RuleCheckOut,
)

if TYPE_CHECKING:
    from green.application.editing import RunContext
    from green.bootstrap.container import Container

# 409: контекст правки прогона не сохранён (прогон не закончен, сделан прежней версией, удалён).
router = APIRouter(
    prefix="/runs",
    tags=["edits"],
    responses={**PROBLEM_RESPONSES, **conflict_response()},
)


def _context(container: Container, run_id: str) -> RunContext:
    context = container.contexts.get(run_id)
    if context is None:
        raise EditContextLostError(
            "Прогон не открыт для правки: его состояние не сохранено - прогон не закончен, "
            "сделан прежней версией сервиса или его файлы удалены. Запустите прогон заново, "
            "чтобы править план."
        )
    return context


@router.get("/{run_id}/draft")
def draft(run_id: str, response: Response, container: ContainerDep) -> DraftOut:
    context = _context(container, run_id)
    plan = context.plan
    response.headers["Cache-Control"] = "no-store"
    return DraftOut(
        plan=plan_payload(plan),
        quality=quality_payload(plan.quality, plan.effect),
        stale=context.report is None or plan is not context.report.plan,
    )


@router.post("/{run_id}/check")
def check(run_id: str, payload: CheckIn, container: ContainerDep) -> CheckOut:
    """Проверить точку по нормам: тем же индексом ограничений, что и сам прогон."""
    context = _context(container, run_id)
    species = container.species.get(payload.species) if payload.species else None
    verdict = check_point(context, payload.x, payload.y, species)
    return CheckOut(
        verdict=verdict.verdict,
        plantable=verdict.plantable,
        needs_barrier=verdict.needs_barrier,
        note=verdict.note,
        checks=[RuleCheckOut.from_check(c) for c in verdict.checks],
    )


@router.post("/{run_id}/edits")
def edit(run_id: str, payload: EditsIn, container: ContainerDep) -> PlanSummaryOut:
    """Применить правки к плану прогона. DXF при этом не переписывается."""
    context = _context(container, run_id)
    edits = [
        Edit(
            kind=EditKind(item.kind),
            placement_id=item.placement_id,
            x=item.x,
            y=item.y,
            species_code=item.species,
        )
        for item in payload.edits
    ]
    context.plan = apply_edits(context, edits, container.species.all())
    return PlanSummaryOut.from_plan(context.plan, stale=True)


@router.post("/{run_id}/rebuild", status_code=202)
def rebuild(
    run_id: str, response: Response, background: BackgroundTasks, container: ContainerDep
) -> PlanSummaryOut:
    """Переписать result.dxf и все артефакты по исправленному плану. Статус: GET /runs/{id}."""
    context = _context(container, run_id)
    background.add_task(container.runs.rebuild, run_id)
    response.headers["Location"] = f"/api/v1/runs/{run_id}"
    return PlanSummaryOut.from_plan(context.plan, stale=True)
