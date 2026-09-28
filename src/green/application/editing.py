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

import math
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.application.assortment import conditions
from green.application.assortment.context import site_context
from green.application.assortment.filters import species_verdict
from green.application.assortment.reassessment import NOT_ON_SOIL, reassess_placements
from green.application.assortment.summary import refresh_summaries
from green.application.barriers import BARRIER_NOTE, barrier_distance
from green.application.constraints import ConstraintIndex
from green.application.effect import street_effect
from green.application.errors import InputError
from green.application.explain import explain
from green.application.lawns import plan_lawns
from green.application.params import active_distance_rules, species_distance_rules
from green.application.places import place_map, with_places
from green.application.quality import assess, site_of
from green.application.surfaces import build_surface_map
from green.application.validation import validate_plan
from green.domain.norms import PlantingType
from green.domain.planting import CheckOutcome, Placement, Rejection, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from green.application.params import PlanParams
    from green.application.ports import InventoryCounts, RunContextStore
    from green.application.quality import Site
    from green.application.results import RunReport
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Plan, RuleCheck, Species

PLACEMENT_PREFIX = "P"


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
    planting_type: PlantingType | None = None


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
    # Перечётка прогона: «было» баланса после правки то же, что при прогоне.
    inventory: InventoryCounts | None = None
    # Карта покрытий не зависит от вида и строится долго, поэтому считается один раз.
    _surface: SurfaceMap | None = field(default=None, repr=False)
    _surface_built: bool = field(default=False, repr=False)
    _indexes: dict[str, ConstraintIndex] = field(default_factory=dict, repr=False)
    # Участок для индекса качества: граница работ и борта, от вида не зависит.
    _site: Site | None = field(default=None, repr=False)

    @property
    def stale(self) -> bool:
        """Only a successfully saved immutable plan can be current on disk."""
        return self.report is None or self.plan is not self.report.plan

    def site(self) -> Site:
        if self._site is None:
            self._site = site_of(
                self.features, self.surface_map(), crown_m=self.params.existing_crown_m
            )
        return self._site

    def surface_map(self) -> SurfaceMap | None:
        """Карта покрытий прогона - та же, что у размещения; строится не больше одного раза.

        Её же берёт проверка правленого плана: иначе каждая правка строила бы карту заново
        (на улице пилота - десятки секунд на одно перетаскивание)."""
        if not self.params.require_soil:
            return None
        if not self._surface_built:
            return self._surface_map(self.index_for(None))
        return self._surface

    def index_for(
        self, species: Species | None, kind: PlantingType | None = None
    ) -> ConstraintIndex:
        """Индекс ограничений для конкретного вида: состав правил зависит от вида и кроны."""
        kind = kind or (
            (PlantingType.TREE if species.is_tree else PlantingType.SHRUB)
            if species
            else self.params.planting_type
        )
        key = f"{species.code if species else ''}:{kind}"
        cached = self._indexes.get(key)
        if cached is not None:
            return cached
        params = replace(self.params, planting_type=kind)
        rules = (
            species_distance_rules(self.rulebook, params, species)
            if species
            else active_distance_rules(self.rulebook, params)
        )
        index = ConstraintIndex(
            self.features,
            rules,
            require_utility_data=self.params.require_utility_data,
            require_soil=self.params.require_soil,
            require_work_boundary=self.params.require_work_boundary,
            planting_radius_m=params.footprint_radius_m,
            barrier_distance_m=barrier_distance(species.height_m)
            if species and params.root_barriers
            else None,
        )
        if self.params.require_soil:
            index.surface = self._surface_map(index)
        self._indexes[key] = index
        return index

    def _surface_map(self, index: ConstraintIndex) -> SurfaceMap | None:
        if not self._surface_built:
            self._surface = build_surface_map(
                self.features,
                self.labels,
                index.boundary,
                self.params.surface_cell_m,
                max_distance_m=self.params.surface_max_distance_m,
                ambiguity_m=self.params.surface_ambiguity_m,
                tree_distance_m=self.params.tree_seed_distance_m,
                inference_mode=self.params.surface_inference_mode,
            )
            self._surface_built = True
        return self._surface


class RunContextCache:
    """Контексты последних прогонов. Размер маленький намеренно: сцена генплана весит сотни МБ.

    С хранилищем контекст прогона после записи результата лежит и на диске, и прогон,
    вытесненный из памяти или сделанный до перезапуска сервиса, поднимается оттуда при первой
    правке: иначе жюри, поднявшее сервис заново, не могло бы править ни один прогон.
    """

    def __init__(self, size: int = 1, store: RunContextStore | None = None) -> None:
        self._size = max(size, 1)
        self._items: OrderedDict[str, RunContext] = OrderedDict()
        self._store = store

    def put(self, context: RunContext) -> None:
        """Запомнить контекст; с хранилищем - и сохранить: прогон закончен или пересобран."""
        self._remember(context)
        if self._store is not None:
            self._store.save(context)

    def get(self, run_id: str) -> RunContext | None:
        context = self._items.get(run_id)
        if context is not None:
            self._items.move_to_end(run_id)
            return context
        context = self._store.load(run_id) if self._store is not None else None
        if context is not None:
            self._remember(context)
        return context

    def _remember(self, context: RunContext) -> None:
        self._items[context.run_id] = context
        self._items.move_to_end(context.run_id)
        while len(self._items) > self._size:
            self._items.popitem(last=False)

    def drop(self, run_id: str) -> None:
        self._items.pop(run_id, None)


def check_point(
    context: RunContext,
    x: float,
    y: float,
    species: Species | None,
    kind: PlantingType | None = None,
) -> PointVerdict:
    """Local footprint/distance/species check; whole-plan quotas/spacing remain separate."""
    if not math.isfinite(x) or not math.isfinite(y):
        raise InputError("Координаты посадки должны быть конечными числами")
    kind = kind or (
        (PlantingType.TREE if species.is_tree else PlantingType.SHRUB)
        if species
        else context.params.planting_type
    )
    index = context.index_for(species, kind)
    points = np.array([shapely.Point(x, y)], dtype=object)
    plantable = bool(index.plantable(points)[0])
    batch = index.evaluate(points)
    verdict = batch.verdict(0) if plantable else Verdict.FORBIDDEN
    note = "" if plantable else NOT_ON_SOIL
    if species is not None:
        candidate = Placement("preview", 0, kind, species, x, y, verdict, batch.checks(0))
        local = species_verdict(
            species,
            site_context(candidate),
            context.rulebook,
            replace(context.params, planting_type=kind),
        )
        if local.blocking is not None:
            verdict = Verdict.FORBIDDEN
            note = " ".join(part for part in (note, local.blocking.text) if part)
    return PointVerdict(
        verdict=verdict,
        checks=batch.checks(0),
        plantable=plantable,
        needs_barrier=batch.needs_barrier(0),
        note=note,
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

    plan = _rebuild_plan(context, [p for p in current if p is not None], catalog)
    plan = refresh_summaries(plan, context.params, catalog)
    # Посадочные места сдвинулись: газон считается заново по той же карте покрытий прогона.
    plan = plan_lawns(
        plan,
        features=context.features,
        labels=context.labels,
        surface=context.surface_map(),
        rulebook=context.rulebook,
        params=context.params,
    )
    return explain(_assess_edited(context, plan, catalog), context.rulebook)


def _assess_edited(context: RunContext, plan: Plan, catalog: Sequence[Species]) -> Plan:
    # Перенесённая и добавленная посадки - в новой точке: место и категория В.6 заново.
    plan = with_places(plan, place_map(context.features))
    validation = validate_plan(
        plan,
        context.features,
        context.labels,
        context.rulebook,
        context.params,
        catalog=catalog,
        existing=plan.assortment_summary.existing if plan.assortment_summary else None,
        surface=context.surface_map(),
    )
    # Keep the draft editable when spacing/quotas need further changes, but do
    # not advertise a quality index or removal advice for an invalid plan.
    plan = assess(plan, context.site(), context.params)
    # Перечётки в контексте правки нет: «было» по деревьям после правки - по чертежу.
    plan = replace(
        plan,
        effect=street_effect(
            plan,
            context.site(),
            context.params,
            getattr(context, "inventory", None),
            surface=context.surface_map(),
            catalog=catalog,
        ),
    )
    if not validation.ok and plan.quality is not None:
        gate = "После правки план не прошёл проверку: " + "; ".join(
            f"{issue.code}: {issue.message}" for issue in validation.issues[:5]
        )
        plan = replace(
            plan,
            quality=replace(
                plan.quality, index=None, gate=gate, values={}, summary=(gate,), analysis=()
            ),
        )
    return plan


def _rebuild_plan(context: RunContext, kept: list[Placement], catalog: Sequence[Species]) -> Plan:
    """Собрать план заново: нарушающая посадка становится отказом, как у генератора.

    Инвариант всего сервиса: на слоях посадок лежит только то, что нормам удовлетворяет.
    Генератор его держит - точка, не прошедшая правила, попадает в отказы. Правка обязана
    держать его тоже, иначе дерево с нарушенным отступом уедет в DXF на слой «требует
    согласования», и в просмотрщике эксперт прочитает нарушение как согласуемое решение.
    """
    refreshed = reassess_placements(
        kept, context.rulebook, catalog, context.params, context.index_for
    )
    good: list[Placement] = []
    violating: list[Placement] = []
    for placement in refreshed:
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
                f"Посадка {p.species.name_ru} после ручной правки не проходит ограничения. "
                + " ".join(p.notes)
            ),
        )
        for i, p in enumerate(violating, 1)
    )
    return replace(
        context.plan,
        placements=placements,
        rejections=(*context.plan.rejections, *moved_out),
        selection=None,
        portfolio=None,
        warnings=(
            *(
                w
                for w in context.plan.warnings
                if not w.startswith(("Условие допуска:", "Кустарники: Условие допуска:"))
            ),
            *conditions(placements),
        ),
    )


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
    verdict = check_point(context, x, y, placement.species, placement.planting_type)
    notes = tuple(n for n in placement.notes if n not in {NOT_ON_SOIL, BARRIER_NOTE})
    if verdict.note:
        notes = (*notes, verdict.note)
    return replace(
        placement,
        x=x,
        y=y,
        verdict=_verdict_of(verdict),
        checks=verdict.checks,
        notes=(
            *notes,
            *((BARRIER_NOTE,) if verdict.needs_barrier else ()),
            "Посадка перенесена вручную, нормы пересчитаны в новой точке.",
        ),
        place="",  # место новой точки определяется заново (_assess_edited)
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
    kind = edit.planting_type or (PlantingType.TREE if species.is_tree else PlantingType.SHRUB)
    if (kind is PlantingType.TREE) != species.is_tree:
        raise InputError("Вид растения не соответствует типу посадки")
    verdict = check_point(context, x, y, species, kind)
    used = {p.placement_id for p in existing if p is not None}
    return Placement(
        placement_id=_next_id(used),
        number=0,  # нумерация выставляется после применения всех правок
        planting_type=kind,
        species=species,
        x=x,
        y=y,
        verdict=_verdict_of(verdict),
        checks=verdict.checks,
        notes=(
            *((verdict.note,) if verdict.note else ()),
            *((BARRIER_NOTE,) if verdict.needs_barrier else ()),
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
