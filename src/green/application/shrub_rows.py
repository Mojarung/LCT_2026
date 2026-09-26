"""Ряд кустарника у борта под кронами аллеи: второй ярус и барьер от пыли дороги.

Полоса от 1 до 2 м от края проезжей части закрыта для деревьев (2,0 м) и открыта для
кустарника (1,0 м): СП 42.13330.2016, табл. 9.1; 743-ПП, табл. 3.6.1. СП 82.13330.2016 п. 9.38
велит озеленять разделительные полосы между проезжей частью и тротуаром, живыми изгородями в
том числе, а МГСН 1.02-02 п. 4.2.9.2 - ставить под кронами ряды кустарника. Заказчик: «аллея
привязана к дороге и многоярусна» (вопрос 15). Ресерч и правила SR-1...SR-18 -
docs/plans/2026-09-22-shrub-row-research.md.

Что сделано в этой версии:

- ряд идёт вдоль борта со стороны аллеи, в пределах её рядов, ось в 1,3 м от борта (норма
  1,0 м плюс запас на снег, вопрос 19), если так не встаёт - в 1,0 м (SR-2);
- шаг 0,4 м (743-ПП, табл. 3.6.2, средние и низкие), изгородь стриженая до 1,0 м (СП 82 п. 9.40);
- каждый куст проходит все нормы кустарника; до ствола дерева не ближе 1,25 м (SR-4), до люка
  не ближе 1,0 м (SR-10);
- на разрыве газона у борта (въезд, проход) ряд отступает на 5 м (SR-9a, Сводный стандарт улиц
  п. 32.12), куски короче 3 м не сажаются (SR-13);
- вид: солестойкий и устойчивый к уплотнению, не колючий, не ядовитый, не массовый аллерген,
  без «-» для улиц в табл. В.6 (SR-16); соседние участки получают разные виды.

Изгородь вдоль всех бортов (curb_hedges): тот же ряд, но не только под кронами аллеи, а везде,
где у борта грунт. Ось - линия на отступе от ближайшего борта (граница буфера всех кусков
борта): пунктирный борт из сотен штрихов даёт сплошную ось, и точка оси не ближе отступа ни к
одному борту. Шаг - 1 м: виды изгороди высокие (выше 1,8 м), для них 743-ПП, табл. 3.6.2 даёт
0,5-1 м. Приём выбран экспериментами docs/notes/30-pipeline-experiments.md (E10, E21).

Чего нет: треугольников видимости у переходов (в топоплане Геотреста переходов нет, SR-9b),
стороны тротуара как запасной (SR-1), просветов у парковок (SR-14).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import KDTree

from green.application.assortment.context import site_context
from green.application.assortment.filters import species_verdict
from green.application.assortment.scoring import percent, score_species
from green.application.params import active_distance_rules
from green.application.placement import (
    MODE_CURB_HEDGE,
    MODE_LABELS,
    MODE_SHRUB_ROW,
    curb_lines,
    planting_index,
)
from green.application.quality.site import WIDE_STREET_M, site_length
from green.application.wording import counted, decimal
from green.domain.norms import PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import (
    SHRUB_FORMS,
    AssortmentInfo,
    Placement,
    Reason,
    Verdict,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry import LineString

    from green.application.assortment.filters import SpeciesVerdict
    from green.application.constraints import ConstraintIndex, EvaluationBatch
    from green.application.params import PlanParams
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Plan, Species

ROW_LABEL = MODE_LABELS[MODE_SHRUB_ROW]
CURB_LABEL = MODE_LABELS[MODE_CURB_HEDGE]
ALLEY_LABEL = MODE_LABELS["alley"]
_CURB_BASIS = "СП 82.13330.2016, п. 9.38; 743-ПП, табл. 3.6.1, 3.6.2"
_REACH_SLACK_M = 0.5  # дерево аллеи относится к борту, если стоит не дальше отступа + запас
# Запас на округление координат до миллиметра (как у групп кустарника в placement.py).
_PIT_RESERVE_M = 0.002
_GIVEN = "given"
_SINGLE = "single"
_BASIS = "СП 82.13330.2016, п. 9.38, 9.40; 743-ПП, табл. 3.6.1, 3.6.2; МГСН 1.02-02, п. 4.2.9.2"


@dataclass(frozen=True, slots=True)
class _Segment:
    points: NDArray[np.float64]
    batch: EvaluationBatch
    rows: tuple[int, ...]  # позиции точек в пачке проверок
    offset_m: float

    @property
    def length_m(self) -> float:
        return float(np.hypot(*(self.points[-1] - self.points[0])))


def fill_shrub_rows(  # noqa: PLR0913 - сценарий передаёт всё, что знает о прогоне
    plan: Plan,
    *,
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    rulebook: RuleBook,
    catalog: Sequence[Species],
    params: PlanParams,
    surface: SurfaceMap | None = None,
) -> Plan:
    if (
        not params.shrub_rows
        or params.planting_type is not PlantingType.TREE
        or params.assortment_mode in {_GIVEN, _SINGLE}
    ):
        return plan
    alley = [
        p
        for p in plan.placements
        if p.planting_type is PlantingType.TREE and ALLEY_LABEL in p.notes
    ]
    lines = curb_lines(features)
    species = _hedge_species(catalog)
    if not lines or not species:
        return plan
    shrub_params = replace(params, planting_type=PlantingType.SHRUB)
    index = planting_index(
        features,
        labels,
        active_distance_rules(rulebook, shrub_params),
        shrub_params,
        surface=surface,
    )
    blockers = Blockers(plan, features, params)
    segments = _segments(alley, lines, index, blockers, params) if alley else []
    planted, skipped = _plant(segments, species, plan, rulebook, shrub_params)
    warnings = list(plan.warnings)
    if planted:
        length = sum(s.length_m for s in segments)
        summary = (
            "Ряды кустарника у борта под кронами аллеи: "
            f"{counted(len(segments) - skipped, 'участок', 'участка', 'участков')}, "
            f"{counted(len(planted), 'куст', 'куста', 'кустов')}, {length:.0f} м ряда "
            "(СП 82.13330.2016, п. 9.38)."
        )
        if skipped:
            summary += (
                f" Без вида осталось участков: {skipped} - ни один солестойкий вид не прошёл нормы."
            )
        warnings.append(summary)
    plan = replace(plan, placements=(*plan.placements, *planted), warnings=tuple(warnings))
    if params.curb_hedges:
        plan = _curb_hedges(
            plan,
            lines,
            index=index,
            features=features,
            species=species,
            rulebook=rulebook,
            params=params,
        )
    return plan


def _curb_hedges(  # noqa: PLR0913 - этап получает всё, что уже собрал ряд под аллеей
    plan: Plan,
    lines: Sequence[LineString],
    *,
    index: ConstraintIndex,
    features: Sequence[Feature],
    species: Sequence[Species],
    rulebook: RuleBook,
    params: PlanParams,
) -> Plan:
    """Изгородь вдоль всех бортов с грунтом: где ряда под аллеей нет."""
    hedge_params = replace(
        params,
        planting_type=PlantingType.SHRUB,
        shrub_row_spacing_m=params.curb_hedge_spacing_m,
    )
    curbs = shapely.union_all(lines)
    base = Blockers(plan, features, hedge_params)
    segments: list[_Segment] = []
    for offset in params.shrub_row_curb_offsets_m:
        # Второй отступ добирает только то, где первый не встал: рядом с уже найденным
        # участком параллельный ряд не нужен.
        blockers = _Near(base, [s.points for s in segments], _PARALLEL_GAP_M)
        ring = shapely.boundary(shapely.buffer(curbs, offset, quad_segs=4))
        for part in shapely.get_parts(ring):
            if part.length < params.shrub_row_min_length_m:
                continue
            # Борт в топоплане - штрихи: кольцо отступа вокруг них волнистое (провалы около
            # сантиметра между штрихами), и станции через 1,002 м по дуге давали 0,996 м по
            # прямой - меньше двух ям куста; проверка снимала каждый второй куст. Ось
            # сглаживается на 5 см, дальше полосы грунта это не уводит.
            axis = shapely.LineString(shapely.get_coordinates(part)).simplify(_AXIS_SMOOTH_M)
            segments += _runs(axis, offset, index=index, blockers=blockers, params=hedge_params)
    segments, capped = _within_budget(segments, plan, index, params)
    planted, skipped = _plant(
        segments,
        species,
        plan,
        rulebook,
        replace(hedge_params, planting_type=PlantingType.SHRUB),
        kind=_Kind("C", "curb", CURB_LABEL, "живая изгородь вдоль борта", _CURB_BASIS),
    )
    if not planted:
        return plan
    length = sum(s.length_m for s in segments)
    summary = (
        "Живая изгородь вдоль бортов: "
        f"{counted(len(segments) - skipped, 'участок', 'участка', 'участков')}, "
        f"{counted(len(planted), 'куст', 'куста', 'кустов')}, "
        f"{length:.0f} м (СП 82.13330.2016, п. 9.38; шаг {params.curb_hedge_spacing_m:g} м - "
        "743-ПП, табл. 3.6.2, высокие кустарники)."
    ).replace(".0 м", " м")
    if capped:
        summary += (
            f" Не посажено участков: {capped} - кустарников на улице было бы больше "
            f"{params.density_shrubs_per_km[1]:g} на 1 км (МГСН 1.02-02, табл. В.1)."
        )
    return replace(
        plan, placements=(*plan.placements, *planted), warnings=(*plan.warnings, summary)
    )


def _within_budget(
    segments: list[_Segment], plan: Plan, index: ConstraintIndex, params: PlanParams
) -> tuple[list[_Segment], int]:
    """Участки изгороди, пока кустарников не больше верхней границы В.1 на длину улицы.

    МГСН 1.02-02, табл. В.1: 600-720 кустарников на 1 км улицы; заказчик: «лучший вариант не
    самый плотный». Изгородь добавляется длинными участками вперёд (сплошная изгородь лучше
    обрывков), пока общий счёт кустарников не упрётся в 720 на 1 км. Граница шире улицы (в
    ней дворы) делает длину по границе оценкой сверху, там предел не ставится - как в индексе.
    """
    boundary = index.boundary
    if not params.curb_hedge_density_cap or boundary is None or not segments:
        return segments, 0
    length = site_length(boundary, params)
    if not length or boundary.area / length > WIDE_STREET_M:
        return segments, 0
    shrubs = sum(1 for p in plan.placements if p.planting_type is PlantingType.SHRUB)
    budget = params.density_shrubs_per_km[1] * length / 1000 - shrubs
    kept: list[_Segment] = []
    for segment in sorted(segments, key=lambda s: -len(s.rows)):
        if len(segment.rows) <= budget:
            kept.append(segment)
            budget -= len(segment.rows)
    return kept, len(segments) - len(kept)


# Сглаживание оси изгороди у штрихового борта (см. _curb_hedges).
_AXIS_SMOOTH_M = 0.05

# Ближе этого к участку, найденному на первом отступе, второй отступ ряд не ставит.
_PARALLEL_GAP_M = 0.8


class _Near:
    """Блокировки ряда плюс точки уже найденных участков этого этапа."""

    def __init__(self, base: Blockers, found: Sequence[NDArray[np.float64]], gap: float) -> None:
        self._base = base
        points = np.concatenate(found) if found else np.zeros((0, 2))
        self._tree = shapely.STRtree(shapely.points(points)) if len(points) else None
        self._gap = gap

    def clear(self, points: NDArray[np.object_]) -> NDArray[np.bool_]:
        ok = self._base.clear(points)
        if self._tree is not None and len(points):
            hits = self._tree.query(points, predicate="dwithin", distance=self._gap)
            ok[np.unique(hits[0])] = False
        return ok


@dataclass(frozen=True, slots=True)
class _Kind:
    """Чем участки этого приёма подписаны: префикс номеров, структура, метка, основание."""

    prefix: str
    structure: str
    label: str
    purpose: str
    basis: str


_ALLEY_ROW = _Kind("H", "hedge", ROW_LABEL, "второй ярус под кронами аллеи", _BASIS)


def _hedge_species(catalog: Sequence[Species]) -> list[Species]:
    """Виды для изгороди у борта (SR-16): соль и уплотнение 2, без колючек, яда, «-» для улиц."""
    return sorted(
        (
            s
            for s in catalog
            if s.life_form in SHRUB_FORMS
            and s.salt_tolerance >= 2  # noqa: PLR2004 - высшая степень шкалы 0-2
            and s.compaction_tolerance >= 2  # noqa: PLR2004
            and s.gas_tolerance >= 1
            and not s.thorny
            and not s.toxic
            and s.allergen < 2  # noqa: PLR2004 - массовый аллерген запрещён 743-ПП п. 3.6.18
            and s.categories.get("streets") != "minus"
        ),
        key=lambda s: s.code,
    )


class Blockers:
    """Что ряд не должен задевать: стволы деревьев, люки и уже посаженные кустарники."""

    def __init__(self, plan: Plan, features: Sequence[Feature], params: PlanParams) -> None:
        trees = [
            shapely.Point(p.x, p.y) for p in plan.placements if p.planting_type is PlantingType.TREE
        ]
        trees += [
            f.geometry.centroid for f in features if f.object_class is ObjectClass.EXISTING_TREE
        ]
        self._trees = shapely.STRtree(trees) if trees else None
        access = [f.geometry for f in features if f.object_class is ObjectClass.UTILITY_ACCESS]
        self._access = shapely.STRtree(access) if access else None
        shrubs = [
            shapely.Point(p.x, p.y)
            for p in plan.placements
            if p.planting_type is PlantingType.SHRUB
        ]
        self._shrubs = shapely.STRtree(shrubs) if shrubs else None
        self._params = params

    def clear(self, points: NDArray[np.object_]) -> NDArray[np.bool_]:
        ok = np.ones(len(points), dtype=bool)
        params = self._params
        # Ямы не перекрываются: до ствола - сумма радиусов посадочных мест дерева и куста, до
        # соседнего куста - два радиуса куста, как у проверки плана (validation).
        tree_pits = params.planting_radius_m + params.shrub_planting_radius_m + _PIT_RESERVE_M
        checks = (
            (self._trees, max(params.shrub_row_tree_gap_m, tree_pits)),
            (self._access, params.shrub_row_access_gap_m),
            (self._shrubs, max(params.shrub_row_spacing_m * 0.9, row_step(params))),
        )
        for tree, gap in checks:
            if tree is None or gap <= 0 or not len(points):
                continue
            hits = tree.query(points, predicate="dwithin", distance=gap)
            ok[np.unique(hits[0])] = False
        return ok


def _segments(
    alley: Sequence[Placement],
    curbs: Sequence[LineString],
    index: ConstraintIndex,
    blockers: Blockers,
    params: PlanParams,
) -> list[_Segment]:
    """Участки ряда вдоль всех цепочек аллеи.

    Ось ряда строится от деревьев, а не от линии борта: борт в топоплане бывает пунктиром из
    сотен кусков, а дерево аллеи всегда знает свой ближайший борт. Для каждого дерева берётся
    ближайшая точка борта, от неё откладывается отступ в сторону дерева; точки, соединённые по
    порядку деревьев, и есть ось ряда - она повторяет изгиб улицы.
    """
    parts = np.array(curbs, dtype=object)
    tree = shapely.STRtree(parts)
    reach = max(params.curb_offsets_m) + _REACH_SLACK_M
    xy = np.array([(p.x, p.y) for p in alley], dtype=np.float64)
    result: list[_Segment] = []
    for chain in _chains(xy, params.spacing_m * 1.5):
        points = shapely.points(xy[chain])
        pairs = tree.query_nearest(points, max_distance=reach, all_matches=False)
        if not len(pairs[0]):
            continue
        feet = shapely.get_coordinates(
            shapely.shortest_line(parts[pairs[1]], points[pairs[0]])
        ).reshape(-1, 2, 2)[:, 0]
        near = np.full(len(chain), -1, dtype=np.int64)
        near[pairs[0]] = np.arange(len(pairs[0]))
        # Дерево без борта рядом рвёт цепочку: ряд у борта там строить не от чего.
        for run in _runs_of(near >= 0):
            ids = [int(near[k]) for k in run]
            trunks = xy[[chain[k] for k in run]]
            result += _best_offset(trunks, feet[ids], index=index, blockers=blockers, params=params)
    return result


def _chains(xy: NDArray[np.float64], link: float) -> list[list[int]]:
    """Цепочки аллеи: соседи ближе link, порядок - вдоль главной оси цепочки."""
    if not len(xy):
        return []
    pairs = KDTree(xy).query_pairs(link, output_type="ndarray")
    size = len(xy)
    if len(pairs):
        graph = coo_matrix(
            (np.ones(len(pairs), dtype=np.int8), (pairs[:, 0], pairs[:, 1])), shape=(size, size)
        )
        _, labels = connected_components(graph, directed=False)
    else:
        labels = np.arange(size)
    chains = []
    for label in np.unique(labels):
        ids = np.flatnonzero(labels == label)
        centered = xy[ids] - xy[ids].mean(axis=0)
        axis = np.linalg.svd(centered, full_matrices=False)[2][0] if len(ids) > 1 else np.ones(2)
        chains.append(ids[np.argsort(centered @ axis, kind="stable")].tolist())
    return chains


def _runs_of(mask: NDArray[np.bool_]) -> list[list[int]]:
    """Сплошные отрезки True по порядку."""
    runs: list[list[int]] = []
    current: list[int] = []
    for k, on in enumerate(mask.tolist()):
        if on:
            current.append(k)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _best_offset(
    trunks: NDArray[np.float64],
    feet: NDArray[np.float64],
    *,
    index: ConstraintIndex,
    blockers: Blockers,
    params: PlanParams,
) -> list[_Segment]:
    """Из отступов от борта берётся тот, что даёт самый длинный ряд; при равенстве - первый."""
    best: list[_Segment] = []
    for offset in params.shrub_row_curb_offsets_m:
        axis = _axis(trunks, feet, offset, params.spacing_m / 2)
        if axis is None:
            continue
        found = _runs(axis, offset, index=index, blockers=blockers, params=params)
        if sum(s.length_m for s in found) > sum(s.length_m for s in best) + 1e-6:
            best = found
    return best


def _axis(
    trunks: NDArray[np.float64], feet: NDArray[np.float64], offset: float, extend: float
) -> LineString | None:
    """Ось ряда: точки борта, сдвинутые к деревьям на offset, с запасом по краям."""
    towards = trunks - feet
    distance = np.hypot(towards[:, 0], towards[:, 1])
    keep = distance > offset + 1e-6  # дерево должно стоять дальше от борта, чем ряд
    if not keep.any():
        return None
    unit = towards[keep] / distance[keep][:, None]
    vertices = feet[keep] + unit * offset
    if len(vertices) == 1:
        along = np.array([-unit[0, 1], unit[0, 0]])
        vertices = np.vstack([vertices[0] - along * extend, vertices[0] + along * extend])
    else:
        head = vertices[0] - vertices[1]
        tail = vertices[-1] - vertices[-2]
        vertices = np.vstack(
            [
                vertices[0] + head / max(np.hypot(*head), 1e-9) * extend,
                vertices,
                vertices[-1] + tail / max(np.hypot(*tail), 1e-9) * extend,
            ]
        )
    return shapely.LineString(vertices)


def _runs(
    axis: LineString,
    offset: float,
    *,
    index: ConstraintIndex,
    blockers: Blockers | _Near,
    params: PlanParams,
) -> list[_Segment]:
    step = row_step(params)
    stations = np.arange(0.0, axis.length + 1e-9, step)
    if len(stations) < 2:  # noqa: PLR2004 - ряд начинается с двух кустов
        return []
    xy = shapely.get_coordinates(shapely.line_interpolate_point(axis, stations))
    points = shapely.points(xy)
    soil = index.plantable(points)
    batch = index.evaluate(points)
    accepted = (
        {Verdict.ALLOWED, Verdict.NEEDS_APPROVAL}
        if params.allow_needs_approval
        else {Verdict.ALLOWED}
    )
    verdict_ok = np.array([batch.verdict(k) in accepted for k in range(len(points))])
    ok = soil & verdict_ok & blockers.clear(points)
    trim = math.ceil(params.shrub_row_gap_buffer_m / step)
    # Разрыв газона - въезд или проход, если грунта нет на ширину проезда. Меньше - зубец
    # растра карты покрытий у борта (ячейка 0,5 м), а не разрыв: от него ряд не отступает.
    wide = math.ceil(params.shrub_row_break_min_m / step)
    segments = []
    for run in _runs_of(ok):
        first, last = run[0], run[-1]
        # Разрыв газона у борта (въезд, проход): ряд отходит от него на gap_buffer (SR-9a).
        if first > 0 and _gap(soil, first - 1, -1) >= wide:
            first += trim
        if last + 1 < len(ok) and _gap(soil, last + 1, 1) >= wide:
            last -= trim
        if last > first and (last - first) * step >= params.shrub_row_min_length_m:
            rows = tuple(range(first, last + 1))
            segments.append(_Segment(xy[first : last + 1], batch, rows, offset))
    return segments


def _gap(soil: NDArray[np.bool_], start: int, direction: int) -> int:
    """Сколько станций подряд без грунта от start в сторону direction."""
    count, k = 0, start
    while 0 <= k < len(soil) and not soil[k]:
        count += 1
        k += direction
    return count


def _plant(  # noqa: PLR0913 - участки, виды, план, нормы и подписи приёма
    segments: Sequence[_Segment],
    species: Sequence[Species],
    plan: Plan,
    rulebook: RuleBook,
    params: PlanParams,
    *,
    kind: _Kind = _ALLEY_ROW,
) -> tuple[list[Placement], int]:
    """Вид на участок целиком; соседний участок по возможности другого вида."""
    planted: list[Placement] = []
    number = len(plan.placements)
    previous: str | None = None
    skipped = 0
    # Сколько кустов каждого вида уже в плане: при балансировке участок получает самый редкий
    # из допустимых видов, иначе два лучших вида по очереди забирают всю изгородь и ломают
    # квоты разнообразия кустарников.
    used: Counter[str] = Counter(
        p.species.code for p in plan.placements if p.planting_type is PlantingType.SHRUB
    )
    for n, segment in enumerate(segments, start=1):
        structure = f"{kind.structure}-{n}"
        drafts = [
            Placement(
                placement_id=f"{kind.prefix}{n:03d}-{i:03d}",
                number=0,
                planting_type=PlantingType.SHRUB,
                species=species[0],
                x=float(x),
                y=float(y),
                verdict=segment.batch.verdict(row),
                checks=segment.batch.checks(row),
                notes=(kind.label,),
            )
            for i, ((x, y), row) in enumerate(zip(segment.points, segment.rows, strict=True))
        ]
        contexts = [site_context(d, structure, "row") for d in drafts]
        ranked = ranked_species(species, contexts, rulebook, params)
        if not ranked:
            skipped += 1
            continue
        if params.hedge_species_balance:
            plain = [r for r in ranked if not _conditional(r[1])] or ranked
            choice = min(plain, key=lambda r: (used[r[0].code], -r[2], r[0].code))
        else:
            choice = next((r for r in ranked if r[0].code != previous), ranked[0])
        chosen, verdicts, _ = choice
        previous = chosen.code
        used[chosen.code] += len(drafts)
        reason = Reason(
            "reference",
            (
                f"живая изгородь у борта: ось в {decimal(segment.offset_m)} м от борта, шаг "
                f"{decimal(row_step(params))} м, стрижка не выше "
                f"{decimal(params.shrub_row_height_m)} м; {kind.purpose}"
            ).replace(".", ","),
            source=kind.basis,
        )
        for draft, verdict, ctx in zip(drafts, verdicts, contexts, strict=True):
            number += 1
            detail = score_species(chosen, ctx, params)
            planted.append(
                replace(
                    draft,
                    number=number,
                    species=chosen,
                    assortment=AssortmentInfo(
                        status="assigned",
                        percent=percent(detail),
                        factors=detail.factors,
                        structure_id=structure,
                        structure_kind="row",
                        reasons=(*verdict.reasons, reason),
                    ),
                )
            )
    return planted, skipped


def ranked_species(
    species: Sequence[Species],
    contexts: Sequence,
    rulebook: RuleBook,
    params: PlanParams,
) -> list[tuple[Species, list[SpeciesVerdict], float]]:
    """Виды, допустимые во всех точках участка, по средней оценке пригодности."""
    ranked = []
    for candidate in species:
        verdicts = [species_verdict(candidate, ctx, rulebook, params) for ctx in contexts]
        if not all(v.allowed for v in verdicts):
            continue
        mean = sum(score_species(candidate, ctx, params).total for ctx in contexts) / len(contexts)
        ranked.append((candidate, verdicts, mean))
    # Вид без условий посадки (не группа III 369-ПП, не мужские клоны) идёт первым: условие -
    # это обязательство на годы, а у изгороди у борта альтернатива обычно есть.
    ranked.sort(key=lambda item: (_conditional(item[1]), -item[2], item[0].code))
    return ranked


def _conditional(verdicts: Sequence[SpeciesVerdict]) -> bool:
    return any(reason.condition for verdict in verdicts for reason in verdict.reasons)


__all__ = ["CURB_LABEL", "ROW_LABEL", "Blockers", "fill_shrub_rows", "ranked_species"]


def row_step(params: PlanParams) -> float:
    """Шаг кустов в ряду: норма ряда (743-ПП, табл. 3.6.2), но не меньше двух радиусов
    посадочного места куста - ямы соседних кустов не перекрываются, как требует проверка."""
    return max(params.shrub_row_spacing_m, 2 * params.shrub_planting_radius_m + _PIT_RESERVE_M)
