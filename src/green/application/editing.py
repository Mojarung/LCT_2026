"""Правка готового плана: перенос, удаление и добавление посадки с пересчётом норм.

Проверка точки идёт через тот же `ConstraintIndex`, что и сам прогон, а не через отдельную
«быструю» реализацию: две реализации одной нормы неизбежно разойдутся, и разойдутся молча -
карта покажет «допускается» там, где генератор отказал.

Контекст прогона (объекты подосновы, параметры, свод норм) держится в памяти процесса. Сцену
не восстановить из артефактов, а перечитывать чертёж на каждое перетаскивание нельзя: чтение
Берзарина занимает 37 секунд. Поэтому правка доступна, пока контекст жив; когда его нет,
сервис честно отвечает 409, а не делает вид, что проверил.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.application.constraints import ConstraintIndex
from green.application.errors import InputError
from green.application.explain import explain
from green.application.params import active_distance_rules
from green.application.surfaces import build_surface_map
from green.domain.norms import PlantingType
from green.domain.planting import CheckOutcome, Placement, Rejection, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from green.application.params import PlanParams
    from green.application.results import RunReport
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Plan, RuleCheck, Species

PLACEMENT_PREFIX = "P"
NOT_ON_SOIL = "Точка вне грунта или вне границы работ: посадочное место здесь не рассматривается."


class EditKind(StrEnum):
    MOVE = "move"
    DELETE = "delete"
    ADD = "add"


@dataclass(frozen=True, slots=True)
class Edit:
    """Одна правка от пользователя. Координаты - в единицах чертежа (метры)."""

    kind: EditKind
    placement_id: str | None = None
    x: float | None = None
    y: float | None = None
    species_code: str | None = None
    planting_type: PlantingType = PlantingType.TREE


@dataclass(frozen=True, slots=True)
class PointVerdict:
    """Ответ на вопрос «можно ли сюда»: вердикт, трасса правил и причина, если нельзя."""

    verdict: Verdict
    checks: tuple[RuleCheck, ...]
    plantable: bool
    needs_barrier: bool
    note: str = ""


@dataclass(slots=True)
class RunContext:
    """Состояние прогона, достаточное для пересчёта норм в произвольной точке."""

    run_id: str
    features: tuple[Feature, ...]
    labels: tuple[TextLabel, ...]
    params: PlanParams
    rulebook: RuleBook
    plan: Plan
    source: Path
    unit_m: float
    # Отчёт исходного прогона: нужен, чтобы пересобрать результат по исправленному плану,
    # не перечитывая чертёж. Ссылку на сам контекст из него уже убрали.
    report: RunReport | None = None
    # Карта покрытий не зависит от вида и строится долго, поэтому считается один раз.
    _surface: SurfaceMap | None = field(default=None, repr=False)
    _surface_built: bool = field(default=False, repr=False)
    _indexes: dict[str, ConstraintIndex] = field(default_factory=dict, repr=False)

    def index_for(self, species: Species | None) -> ConstraintIndex:
        """Индекс ограничений для конкретного вида: состав правил зависит от вида и кроны."""
        key = species.code if species else ""
        cached = self._indexes.get(key)
        if cached is not None:
            return cached
        rules = active_distance_rules(
            self.rulebook,
            self.params,
            species.name_lat if species else None,
            species.crown_mature_m if species else None,
            species.traits if species else frozenset(),
        )
        index = ConstraintIndex(
            self.features,
            rules,
            require_utility_data=self.params.require_utility_data,
        )
        if self.params.require_soil:
            index.surface = self._surface_map(index)
        self._indexes[key] = index
        return index

    def _surface_map(self, index: ConstraintIndex) -> SurfaceMap | None:
        if not self._surface_built:
            self._surface = build_surface_map(
                self.features, self.labels, index.boundary, self.params.surface_cell_m
            )
            self._surface_built = True
        return self._surface


class RunContextCache:
    """Контексты последних прогонов. Размер маленький намеренно: сцена генплана весит сотни МБ."""

    def __init__(self, size: int = 1) -> None:
        self._size = max(size, 1)
        self._items: OrderedDict[str, RunContext] = OrderedDict()

    def put(self, context: RunContext) -> None:
        self._items[context.run_id] = context
        self._items.move_to_end(context.run_id)
        while len(self._items) > self._size:
            self._items.popitem(last=False)

    def get(self, run_id: str) -> RunContext | None:
        context = self._items.get(run_id)
        if context is not None:
            self._items.move_to_end(run_id)
        return context

    def drop(self, run_id: str) -> None:
        self._items.pop(run_id, None)


def check_point(context: RunContext, x: float, y: float, species: Species | None) -> PointVerdict:
    """Проверить точку по всем действующим правилам, как это делает прогон."""
    index = context.index_for(species)
    points = np.array([shapely.Point(x, y)], dtype=object)
    plantable = bool(index.plantable(points)[0])
    batch = index.evaluate(points)
    return PointVerdict(
        verdict=batch.verdict(0),
        checks=batch.checks(0),
        plantable=plantable,
        needs_barrier=batch.needs_barrier(0),
        note="" if plantable else NOT_ON_SOIL,
    )


def apply_edits(context: RunContext, edits: Sequence[Edit], catalog: Sequence[Species]) -> Plan:
    """Применить правки к плану и пересобрать вердикты, нумерацию и объяснения.

    Удалённые посадки на время обработки остаются дырой в списке, а не исчезают: иначе
    позиции следующих правок в той же пачке съезжают и правка приходится не на ту посадку.
    """
    by_code = {s.code: s for s in catalog}
    current: list[Placement | None] = list(context.plan.placements)
    positions = {p.placement_id: i for i, p in enumerate(context.plan.placements)}

    for edit in edits:
        if edit.kind is EditKind.ADD:
            added = _added(context, edit, by_code, current)
            current.append(added)
            positions[added.placement_id] = len(current) - 1
            continue
        position = _require_existing(positions, edit)
        if edit.kind is EditKind.DELETE:
            current[position] = None
            positions.pop(_placement_id(edit))
        else:
            current[position] = _moved(context, _at(current, position, edit), edit)

    return _rebuild_plan(context, [p for p in current if p is not None])


def _rebuild_plan(context: RunContext, kept: list[Placement]) -> Plan:
    """Собрать план заново: нарушающая посадка становится отказом, как у генератора.

    Инвариант всего сервиса: на слоях посадок лежит только то, что нормам удовлетворяет.
    Генератор его держит - точка, не прошедшая правила, попадает в отказы. Правка обязана
    держать его тоже, иначе дерево с нарушенным отступом уедет в DXF на слой «требует
    согласования», и в просмотрщике эксперт прочитает нарушение как согласуемое решение.
    """
    good: list[Placement] = []
    violating: list[Placement] = []
    for placement in kept:
        (violating if placement.verdict is Verdict.FORBIDDEN else good).append(placement)

    placements = tuple(replace(p, number=i) for i, p in enumerate(good, 1))
    start = len(context.plan.rejections)
    moved_out = tuple(
        Rejection(
            rejection_id=p.placement_id,
            number=start + i,
            planting_type=p.planting_type,
            x=p.x,
            y=p.y,
            verdict=p.verdict,
            blocking=tuple(c for c in p.checks if c.outcome is CheckOutcome.FAIL),
            note=(
                f"Посадка {p.species.name_ru} перенесена сюда вручную, но норму здесь "
                f"выдержать нельзя, поэтому место отмечено как отказ."
            ),
        )
        for i, p in enumerate(violating, 1)
    )
    plan = replace(
        context.plan,
        placements=placements,
        rejections=(*context.plan.rejections, *moved_out),
    )
    return explain(plan, context.rulebook)


def _placement_id(edit: Edit) -> str:
    if not edit.placement_id:
        raise InputError(f"Правка «{edit.kind.value}» требует идентификатора посадки")
    return edit.placement_id


def _require_existing(positions: dict[str, int], edit: Edit) -> int:
    placement_id = _placement_id(edit)
    if placement_id not in positions:
        raise InputError(f"Посадка {placement_id} в плане не найдена")
    return positions[placement_id]


def _at(current: Sequence[Placement | None], position: int, edit: Edit) -> Placement:
    placement = current[position]
    if placement is None:
        raise InputError(f"Посадка {_placement_id(edit)} уже удалена в этой же пачке правок")
    return placement


def _coordinates(edit: Edit) -> tuple[float, float]:
    if edit.x is None or edit.y is None:
        raise InputError(f"Правка «{edit.kind.value}» требует координат x и y")
    return float(edit.x), float(edit.y)


def _moved(context: RunContext, placement: Placement, edit: Edit) -> Placement:
    x, y = _coordinates(edit)
    verdict = check_point(context, x, y, placement.species)
    notes = tuple(n for n in placement.notes if n != NOT_ON_SOIL)
    if verdict.note:
        notes = (*notes, verdict.note)
    return replace(
        placement,
        x=x,
        y=y,
        verdict=_verdict_of(verdict),
        checks=verdict.checks,
        notes=(*notes, "Посадка перенесена вручную, нормы пересчитаны в новой точке."),
    )


def _added(
    context: RunContext,
    edit: Edit,
    by_code: dict[str, Species],
    existing: Sequence[Placement | None],
) -> Placement:
    x, y = _coordinates(edit)
    if not edit.species_code:
        raise InputError("Добавление посадки требует кода вида")
    species = by_code.get(edit.species_code)
    if species is None:
        raise InputError(f"Вид {edit.species_code} отсутствует в каталоге")
    verdict = check_point(context, x, y, species)
    used = {p.placement_id for p in existing if p is not None}
    return Placement(
        placement_id=_next_id(used),
        number=0,  # нумерация выставляется после применения всех правок
        planting_type=edit.planting_type,
        species=species,
        x=x,
        y=y,
        verdict=_verdict_of(verdict),
        checks=verdict.checks,
        notes=(
            *((verdict.note,) if verdict.note else ()),
            "Посадка добавлена вручную, нормы проверены в этой точке.",
        ),
    )


def _verdict_of(point: PointVerdict) -> Verdict:
    """Точка вне грунта не становится допустимой от того, что до сетей далеко."""
    if not point.plantable:
        return Verdict.FORBIDDEN
    return point.verdict


def _next_id(used: set[str]) -> str:
    number = len(used) + 1
    while f"{PLACEMENT_PREFIX}{number:05d}" in used:
        number += 1
    return f"{PLACEMENT_PREFIX}{number:05d}"


__all__ = [
    "Edit",
    "EditKind",
    "PointVerdict",
    "RunContext",
    "RunContextCache",
    "apply_edits",
    "check_point",
]
