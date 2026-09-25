"""Стратегия размещения: жадный отбор кандидатов двух приёмов по одним и тем же правилам.

Приём «alley»: рядовая посадка вдоль бортового камня, станции по линиям и штрихам борта,
отступы из профиля с обеих сторон. Приём «lawn»: заполнение грунта шахматной сеткой с шагом
посадки по карте покрытий, как сажают проектировщики во дворах. Приём «fill»: добор зоны -
сетка с шагом шесть метров пропускает узкие полосы и карманы газона, поэтому после неё
проверяются все ячейки грунта через метр, сначала те, где запас до сетей больше. Все приёмы
проверяются одним ConstraintIndex, посадки держат шаг между собой. Результат детерминирован.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol

import numpy as np
import shapely

from green.application.approximation import reserved_buffer
from green.application.barriers import BARRIER_NOTE, NEAR_M, barrier_distance
from green.application.candidate_selection import SelectionProblem, select_candidates
from green.application.constraints import ConstraintIndex, EvaluationBatch
from green.application.errors import InputError
from green.application.params import active_distance_rules, species_distance_rules
from green.application.species_norms import species_norms
from green.application.surfaces import Material, build_surface_map
from green.application.zones import MAX_ZONE_POINTS, build_zones, zone_capacity
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Placement, Plan, Rejection, Verdict, Zone

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry import LineString
    from shapely.geometry.base import BaseGeometry

    from green.application.params import PlanParams
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import DistanceRule, RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Species
    from green.domain.selection import SelectionReport

MODE_ALLEY = "alley"
MODE_LAWN = "lawn"
MODE_FILL = "fill"  # добор зоны; посадки подписаны как заполнение газона
MODE_SHRUB_GROUP = "shrub_group"
MODE_SHRUB_ROW = "shrub_row"
MODE_CURB_HEDGE = "curb_hedge"
MODE_UNDERSTORY = "understory"
MODE_SHRUB_FILL = "shrub_fill"
MODE_LABELS = {
    MODE_ALLEY: "аллея вдоль борта",
    MODE_LAWN: "заполнение газона",
    MODE_SHRUB_GROUP: "группа кустарников на месте дерева",
    MODE_SHRUB_ROW: "ряд кустарника у борта под кронами аллеи",
    MODE_CURB_HEDGE: "живая изгородь вдоль борта",
    MODE_UNDERSTORY: "кустарник под кроной дерева",
    MODE_SHRUB_FILL: "группа кустарников на газоне",
}
_TANGENT_STEP_M = 0.5
_SPACING_TOLERANCE = 0.95
_Z_ORDER_BITS = 16
# Two independently rounded XY points can approach by at most sqrt(2) mm.
# Reserve 2 mm when constructing a rotated group, rather than weaken clearance.
_ROUNDING_PAIR_RESERVE_M = 0.002


class PlacementStrategy(Protocol):
    """surface - карта покрытий прогона; None - стратегия строит её сама по тем же параметрам."""

    def plan(  # noqa: PLR0913 - входы прогона плюс его карта покрытий
        self,
        features: Sequence[Feature],
        labels: Sequence[TextLabel],
        rulebook: RuleBook,
        species: Species,
        params: PlanParams,
        *,
        surface: SurfaceMap | None = None,
    ) -> Plan: ...

    def shrub_groups(  # noqa: PLR0913 - те же входы, что у plan, плюс центры групп
        self,
        features: Sequence[Feature],
        labels: Sequence[TextLabel],
        rulebook: RuleBook,
        species: Species,
        params: PlanParams,
        *,
        centers: Sequence[tuple[float, float]],
        surface: SurfaceMap | None = None,
    ) -> tuple[Placement, ...]: ...


@dataclass(frozen=True, slots=True)
class _Candidate:
    station: int
    mode: str
    x: float
    y: float


class GreedyPlantingStrategy:
    """Аллея вдоль борта, затем заполнение газона; первый допустимый вариант на станции."""

    def plan(  # noqa: PLR0913 - входы прогона плюс его карта покрытий
        self,
        features: Sequence[Feature],
        labels: Sequence[TextLabel],
        rulebook: RuleBook,
        species: Species,
        params: PlanParams,
        *,
        surface: SurfaceMap | None = None,
    ) -> Plan:
        # В режиме одного вида видовые нормы проверяются здесь; в режиме подбора - на каждой
        # паре «посадка - вид» (assortment.filters), а вид профиля лишь задаёт отступы по роду.
        single = params.assortment_mode == "single"
        if single:
            norms = species_norms(
                species,
                rulebook,
                params.territory,
                params.planting_category,
                allergen_act_priority=params.allergen_act_priority,
            )
            if norms.blocking is not None:
                raise InputError(
                    f"Вид {species.name_lat} недопустим: {norms.blocking.text} "
                    f"({norms.blocking.rule_id or norms.blocking.source})"
                )
        rules = (
            species_distance_rules(rulebook, params, species)
            if single
            else active_distance_rules(rulebook, params, species.name_lat)
        )
        # Пока вид не выбран, точка проверяется по самому мягкому барьерному расстоянию;
        # подбор ассортимента затем требует своё расстояние по высоте каждого вида.
        barrier = None
        if params.root_barriers:
            barrier = barrier_distance(species.height_m) if single else NEAR_M
        index = ConstraintIndex(
            features,
            rules,
            require_utility_data=params.require_utility_data,
            barrier_distance_m=barrier,
            require_soil=params.require_soil,
            require_work_boundary=params.require_work_boundary,
            planting_radius_m=params.footprint_radius_m,
        )
        if params.require_soil:
            index.surface = surface or _surface_map(features, labels, index, params)
        selector = _Selector(species=species, params=params)
        stats: dict[str, int | float] = {}
        if MODE_ALLEY in params.modes:
            reach = max((abs(offset) for offset in params.curb_offsets_m), default=0.0)
            lines = _curb_lines(features, index.boundary, reach + _ROUNDING_PAIR_RESERVE_M)
            candidates = _curb_candidates(lines, params)
            stats["alley_candidates"] = len(candidates)
            stats["alley_plantable"] = _offer(index, selector, candidates)
        if MODE_LAWN in params.modes and index.surface is not None:
            candidates = _lawn_candidates(index.surface, params)
            stats["lawn_candidates"] = len(candidates)
            stats["lawn_plantable"] = _offer(index, selector, candidates)
        if MODE_FILL in params.modes and index.surface is not None:
            before = len(selector.placements)
            stats["fill_candidates"] = _fill(index, selector, params)
            stats["fill_planted"] = len(selector.placements) - before
        selection = selector.optimize() if params.placement_solver == "milp" else None
        zones = _zones(index, params, stats)
        return Plan(
            placements=tuple(selector.placements),
            rejections=tuple(selector.rejections),
            warnings=_warnings(
                features, index, selector.rejections, params, disabled_rules_note(rulebook, params)
            ),
            stats=stats,
            zones=zones,
            selection=selection,
        )

    def shrub_groups(  # noqa: PLR0913 - те же входы, что у plan, плюс центры групп
        self,
        features: Sequence[Feature],
        labels: Sequence[TextLabel],
        rulebook: RuleBook,
        species: Species,
        params: PlanParams,
        *,
        centers: Sequence[tuple[float, float]],
        surface: SurfaceMap | None = None,
    ) -> tuple[Placement, ...]:
        """Группы кустарников: квадрат size x size с шагом spacing_m вокруг каждого центра.

        Точка группы проверяется так же, как посадка: грунт по карте покрытий, граница работ,
        все правила расстояний для кустарника. Правила по роду здесь не применяются - вид
        ещё не выбран, их проверяет подбор ассортимента. Точка, не прошедшая нормы, просто
        не входит в группу: отказ на месте уже записан для дерева.
        """
        if not centers:
            return ()
        rules = active_distance_rules(rulebook, params)
        index = ConstraintIndex(
            features,
            rules,
            require_utility_data=params.require_utility_data,
            require_soil=params.require_soil,
            require_work_boundary=params.require_work_boundary,
            planting_radius_m=params.footprint_radius_m,
        )
        if params.require_soil:
            index.surface = surface or _surface_map(features, labels, index, params)
        offsets = _shrub_offsets(params)
        candidates = [
            _Candidate(station, MODE_SHRUB_GROUP, round(cx + dx, 3), round(cy + dy, 3))
            for station, (cx, cy) in enumerate(centers)
            for dx, dy in offsets
        ]
        points = shapely.points([(c.x, c.y) for c in candidates])
        positions = np.flatnonzero(index.plantable(points))
        if not len(positions):
            return ()
        batch = index.evaluate(points[positions])
        accepted = {Verdict.ALLOWED}
        if params.allow_needs_approval:
            accepted.add(Verdict.NEEDS_APPROVAL)
        selector = _Selector(species=species, params=params)
        occupied = _Grid(max(params.spacing_m * _SPACING_TOLERANCE, 2 * params.footprint_radius_m))
        for row, position in enumerate(positions.tolist()):
            candidate = candidates[position]
            if batch.verdict(row) in accepted and not occupied.near(candidate.x, candidate.y):
                occupied.add(candidate.x, candidate.y)
                selector.placements.append(selector._placement(candidate, batch, row))  # noqa: SLF001 - same placement representation
        return tuple(selector.placements)


def _shrub_offsets(params: PlanParams) -> list[tuple[float, float]]:
    size = params.shrub_group_size
    spacing = params.spacing_m
    theta = 0.0
    if params.lawn_anchor == "soil":
        theta = math.radians(params.lawn_rotation_deg)
        spacing = max(spacing, 2 * params.footprint_radius_m + _ROUNDING_PAIR_RESERVE_M)
    c, s = math.cos(theta), math.sin(theta)
    offsets = [(i - (size - 1) / 2) * spacing for i in range(size)]
    return [(dx * c - dy * s, dx * s + dy * c) for dx in offsets for dy in offsets]


def _zones(
    index: ConstraintIndex, params: PlanParams, stats: dict[str, int | float]
) -> tuple[Zone, ...]:
    """Зоны допустимости и их сводка в статистике плана."""
    if index.surface is not None:
        stats.update({f"surface_{k}": v for k, v in index.surface.summary().items()})
    zones = build_zones(index, params.zone_cell_m) if params.zones else ()
    for zone in zones:
        stats[f"zone_{zone.verdict.value}_m2"] = round(zone.area_m2)
    # Вместимость зоны - свойство участка; по ней индекс меряет плотность «при условии
    # допустимости насаждений» (МГСН 1.02-02, табл. В.1).
    if zones:
        stats["zone_capacity_trees"] = zone_capacity(zones)
    return zones


def _offer(index: ConstraintIndex, selector: _Selector, candidates: list[_Candidate]) -> int:
    """Проверяет кандидатов пачкой и предлагает отборщику; возвращает число допустимых точек."""
    if not candidates:
        return 0
    # Validate the coordinates that will actually be exported, including spacing.
    candidates = [replace(c, x=round(c.x, 3), y=round(c.y, 3)) for c in candidates]
    points = shapely.points([(c.x, c.y) for c in candidates])
    positions = np.flatnonzero(index.plantable(points))
    if not len(positions):
        return 0
    selector.batch = index.evaluate(points[positions])
    for row, position in enumerate(positions.tolist()):
        selector.offer(candidates[position], row)
    selector.flush()
    return len(positions)


def planting_index(  # noqa: PLR0913 - те же политики, что у независимой проверки плана
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    rules: Sequence[DistanceRule],
    params: PlanParams,
    *,
    surface: SurfaceMap | None = None,
    barrier_distance_m: float | None = None,
) -> ConstraintIndex:
    """Индекс ограничений с теми же требованиями к месту, что у проверки плана (validation):
    грунт, граница работ и посадочное место радиуса footprint_radius_m целиком на грунте.

    Этапы, которые добавляют посадки к готовому плану (ряд кустарника, подлесок, группы на
    газоне, сдвиг слабых мест), строят индекс только так: иначе они ставят то, что проверка
    потом отвергает, и вариант плана целиком не проходит.
    """
    index = ConstraintIndex(
        features,
        rules,
        require_utility_data=params.require_utility_data,
        barrier_distance_m=barrier_distance_m,
        require_soil=params.require_soil,
        require_work_boundary=params.require_work_boundary,
        planting_radius_m=params.footprint_radius_m,
    )
    if params.require_soil:
        index.surface = surface or _surface_map(features, labels, index, params)
    return index


def _surface_map(
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    index: ConstraintIndex,
    params: PlanParams,
) -> SurfaceMap | None:
    """Карта покрытий по границе работ индекса - та же, что строит сценарий прогона."""
    return build_surface_map(
        features,
        labels,
        index.boundary,
        params.surface_cell_m,
        max_distance_m=params.surface_max_distance_m,
        ambiguity_m=params.surface_ambiguity_m,
        tree_distance_m=params.tree_seed_distance_m,
        inference_mode=params.surface_inference_mode,
    )


def curb_lines(features: Sequence[Feature]) -> list[LineString]:
    """Линии бортового камня, сшитые в непрерывные куски, в порядке обхода вдоль улицы.

    Все борта чертежа, без отсечения по границе работ: ряды кустарника и группы на газоне
    отбирают места сами, по карте покрытий и границе."""
    return _curb_lines(features)


def _curb_lines(
    features: Sequence[Feature], boundary: BaseGeometry | None = None, reach_m: float = 0.0
) -> list[LineString]:
    parts = []
    for feature in features:
        if feature.object_class is not ObjectClass.CURB:
            continue
        geometry = feature.geometry
        if geometry.geom_type in {"Polygon", "MultiPolygon"}:
            geometry = geometry.boundary
        parts.extend(_linear_parts(geometry))
    if not parts:
        return []
    if boundary is not None:
        # A station farther away than every offered offset cannot plant inside
        # the site. Clip before noding/merging so remote tails and junctions do
        # not change phases or allocate arrays proportional to the whole city.
        influence = reserved_buffer(boundary, reach_m)
        parts = [
            part
            for clipped in shapely.intersection(parts, influence)
            for part in _linear_parts(clipped)
        ]
    if not parts:
        return []
    merged = shapely.line_merge(shapely.union_all(parts))
    lines = [_canonical_line(line) for line in _linear_parts(merged) if line.length > 0]
    if not lines:
        return []
    centroids = shapely.get_coordinates(shapely.centroid(lines))
    order = np.argsort(_z_order(centroids), kind="stable")
    return [lines[i] for i in order]


def _linear_parts(geometry: BaseGeometry) -> list[LineString]:
    if geometry.geom_type in {"LineString", "LinearRing"}:
        return [] if geometry.is_empty else [geometry]
    if geometry.geom_type in {"MultiLineString", "GeometryCollection"}:
        return [line for part in shapely.get_parts(geometry) for line in _linear_parts(part)]
    return []


def _canonical_line(line: LineString) -> LineString:
    if line.is_ring:
        # A closed LineString has an arbitrary start vertex; polygon ring
        # normalization also fixes that origin, without altering its geometry.
        return shapely.LineString(shapely.normalize(shapely.Polygon(line)).exterior.coords)
    return shapely.normalize(line)


def _z_order(xy: NDArray[np.float64]) -> NDArray[np.uint64]:
    """Кривая Мортона: соседние по плану объекты оказываются рядом в порядке обхода."""
    if not len(xy):
        return np.zeros(0, dtype=np.uint64)
    span = np.maximum(np.ptp(xy, axis=0), 1e-9)
    scaled = ((xy - xy.min(axis=0)) / span * ((1 << _Z_ORDER_BITS) - 1)).astype(np.uint64)
    code = np.zeros(len(xy), dtype=np.uint64)
    for bit in range(_Z_ORDER_BITS):
        mask = np.uint64(1 << bit)
        x_bit = (scaled[:, 0] & mask) << np.uint64(bit)
        y_bit = (scaled[:, 1] & mask) << np.uint64(bit + 1)
        code |= x_bit | y_bit
    return code


def _curb_candidates(lines: list[LineString], params: PlanParams) -> list[_Candidate]:
    """Станции по борту с шагом посадки, на каждой все отступы профиля с обеих сторон."""
    candidates: list[_Candidate] = []
    if not params.curb_offsets_m:
        return candidates
    station = 0
    for line in lines:
        if line.length >= params.spacing_m:
            distances = np.arange(params.spacing_m / 2, line.length, params.spacing_m)
        else:
            distances = np.array([line.length / 2])
        base = _coords(line, distances)
        tangent = _coords(line, np.minimum(distances + _TANGENT_STEP_M, line.length)) - _coords(
            line, np.maximum(distances - _TANGENT_STEP_M, 0.0)
        )
        norms = np.hypot(tangent[:, 0], tangent[:, 1])
        norms[norms == 0] = 1.0
        normal = np.column_stack((-tangent[:, 1], tangent[:, 0])) / norms[:, None]
        for position in range(len(distances)):
            for side in (1.0, -1.0):
                for offset in params.curb_offsets_m:
                    x, y = base[position] + normal[position] * side * offset
                    candidates.append(_Candidate(station, MODE_ALLEY, float(x), float(y)))
                station += 1
    return candidates


def _lawn_candidates(surface: SurfaceMap, params: PlanParams) -> list[_Candidate]:
    """Шахматная сетка с шагом посадки по ячейкам грунта; каждая точка - своя станция."""
    if (
        params.lawn_anchor == "soil"
        or params.lawn_phase != (0.0, 0.0)
        or params.lawn_rotation_deg != 0.0
    ):
        return _oriented_lawn_candidates(surface, params)
    stride = max(1, round(params.spacing_m / surface.cell))
    grid = surface.grid
    candidates: list[_Candidate] = []
    station = 1_000_000  # станции аллеи нумеруются с нуля, здесь свой диапазон
    for row_index, row in enumerate(range(0, grid.shape[0], stride)):
        start = stride // 2 if row_index % 2 else 0
        cols = np.arange(start, grid.shape[1], stride)
        soil = cols[grid[row, cols] == Material.SOIL]
        y = surface.origin[1] + (row + 0.5) * surface.cell
        for col in soil.tolist():
            x = surface.origin[0] + (col + 0.5) * surface.cell
            candidates.append(_Candidate(station, MODE_LAWN, x, y))
            station += 1
    return candidates


def _oriented_lawn_candidates(surface: SurfaceMap, params: PlanParams) -> list[_Candidate]:
    """Continuous staggered lattice in a chosen local frame; the same soil check follows."""
    theta = math.radians(params.lawn_rotation_deg)
    rotation = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    if params.lawn_anchor == "soil" and surface.soil_area is not None:
        # The display raster's world-axis bbox changes under rotation. Anchor
        # the lattice to actual soil projected into the requested frame instead.
        # Subtract a nearby origin before projecting to avoid large CAD offsets.
        outline = shapely.get_coordinates(surface.soil_area)
        if not len(outline) or surface.soil_area.area <= 0:
            return []
        local_outline = (outline - np.asarray(surface.origin)) @ rotation
    else:
        # Legacy distance-inference scenes may only have raster evidence.
        height, width = np.array(surface.grid.shape) * surface.cell
        local_outline = np.array([[0, 0], [width, 0], [width, height], [0, height]]) @ rotation
    low, high = local_outline.min(axis=0), local_outline.max(axis=0)
    start = low + np.asarray(params.lawn_phase) * params.spacing_m + surface.cell / 2
    candidates = []
    for row, v in enumerate(np.arange(start[1], high[1], params.spacing_m)):
        u = np.arange(start[0] + (row % 2) * params.spacing_m / 2, high[0], params.spacing_m)
        local = np.column_stack((u, np.full_like(u, v)))
        world = local @ rotation.T + np.asarray(surface.origin)
        soil = surface.material(shapely.points(world)) == Material.SOIL
        for x, y in world[soil].tolist():
            candidates.append(_Candidate(1_000_000 + len(candidates), MODE_LAWN, x, y))
    return candidates


# Запас до сети сверх этого добору уже не важен: цель запаса - полметра (СП 317.1325800.2017,
# п. 5.3.5.3), дальше места равны и решает порядок обхода, дающий плотную упаковку.
_FILL_SLACK_CAP_M = 1.0


def _fill(index: ConstraintIndex, selector: _Selector, params: PlanParams) -> int:
    """Добор зоны: каждая ячейка грунта через fill_step_m, допустимые - по убыванию запаса.

    Отбираются только точки с принимаемым вердиктом: недопустимые ячейки - это зона запрета,
    отметки отказа на каждой из них засорили бы план. Место принимается, если до всех уже
    поставленных деревьев не меньше шага посадки (тот же отборщик, что у аллеи и газона).
    Порядок: сначала без замечаний, затем с барьером, затем на согласование; внутри - запас
    до сетей (до _FILL_SLACK_CAP_M), при равенстве - построчно.
    """
    surface = index.surface
    if surface is None:
        return 0
    stride = max(1, round(params.fill_step_m / surface.cell))
    soil = surface.grid[::stride, ::stride] == Material.SOIL
    # Чертёж без границы работ (Нижние Поля) - это весь лист: шаг растёт, как у зон.
    while soil.sum() > MAX_ZONE_POINTS:
        stride *= 2
        soil = surface.grid[::stride, ::stride] == Material.SOIL
    rows, cols = np.nonzero(soil)
    xy = np.column_stack(
        [
            surface.origin[0] + (cols * stride + 0.5) * surface.cell,
            surface.origin[1] + (rows * stride + 0.5) * surface.cell,
        ]
    )
    points = shapely.points(xy)
    keep = np.flatnonzero(index.plantable(points))
    if not len(keep):
        return 0
    xy, batch = xy[keep], index.evaluate(points[keep])
    ranks = {Verdict.ALLOWED: 0}
    if params.allow_needs_approval:
        ranks[Verdict.NEEDS_APPROVAL] = 2
    verdicts = [batch.verdict(k) for k in range(len(xy))]
    usable = [k for k in range(len(xy)) if verdicts[k] in ranks]
    slack = batch.slack()
    slack = np.where(np.isfinite(slack), np.minimum(slack, _FILL_SLACK_CAP_M), _FILL_SLACK_CAP_M)
    usable.sort(
        key=lambda k: (ranks[verdicts[k]] + int(batch.needs_barrier(k)), -float(slack[k]), k)
    )
    selector.batch = batch
    station = 2_000_000  # у аллеи и газона свои диапазоны станций
    for k in usable:
        selector.offer(_Candidate(station, MODE_LAWN, float(xy[k, 0]), float(xy[k, 1])), k)
        station += 1
    selector.flush()
    return len(usable)


def _coords(line: LineString, distances: NDArray[np.float64]) -> NDArray[np.float64]:
    return shapely.get_coordinates(shapely.line_interpolate_point(line, distances))


class _Grid:
    """Проверка «есть ли точка ближе gap» за O(1) на ячейку."""

    def __init__(self, gap: float) -> None:
        self._gap = gap
        self._cells: dict[tuple[int, int], list[tuple[float, float]]] = {}

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return math.floor(x / self._gap), math.floor(y / self._gap)

    def near(self, x: float, y: float) -> bool:
        cx, cy = self._cell(x, y)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for px, py in self._cells.get((cx + dx, cy + dy), ()):
                    if math.hypot(px - x, py - y) < self._gap:
                        return True
        return False

    def add(self, x: float, y: float) -> None:
        self._cells.setdefault(self._cell(x, y), []).append((x, y))


@dataclass(slots=True)
class _Selector:
    """Обходит станции по порядку: принимает первый допустимый вариант, дедуплицирует отказы."""

    species: Species
    params: PlanParams
    batch: EvaluationBatch | None = None
    placements: list[Placement] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    _station: int | None = None
    _options: list[tuple[_Candidate, int]] = field(default_factory=list)
    _planted: _Grid | None = None
    _refused: _Grid | None = None
    _eligible: list[tuple[_Candidate, EvaluationBatch, int]] = field(default_factory=list)
    _chosen: list[_Candidate] = field(default_factory=list)

    def offer(self, candidate: _Candidate, row: int) -> None:
        if candidate.station != self._station:
            self.flush()
            self._station = candidate.station
        self._options.append((candidate, row))
        batch = self.batch
        if self.params.placement_solver == "milp" and batch is not None:
            accepted = {Verdict.ALLOWED}
            if self.params.allow_needs_approval:
                accepted.add(Verdict.NEEDS_APPROVAL)
            if batch.verdict(row) in accepted:
                self._eligible.append((candidate, batch, row))

    def flush(self) -> None:
        batch = self.batch
        if not self._options or batch is None:
            return
        options, self._options = self._options, []
        gap = max(self.params.spacing_m * _SPACING_TOLERANCE, 2 * self.params.footprint_radius_m)
        planted = self._planted = self._planted or _Grid(gap)
        refused = self._refused = self._refused or _Grid(gap)
        ranks = [Verdict.ALLOWED]
        if self.params.allow_needs_approval:
            ranks.append(Verdict.NEEDS_APPROVAL)

        # Сначала вариант без замечаний, затем с прикорневым барьером, затем с согласованием.
        for verdict in ranks:
            for with_barrier in (False, True):
                for candidate, row in options:
                    if batch.verdict(row) is not verdict:
                        continue
                    if batch.needs_barrier(row) is not with_barrier:
                        continue
                    if not planted.near(candidate.x, candidate.y):
                        planted.add(candidate.x, candidate.y)
                        self.placements.append(self._placement(candidate, batch, row))
                        self._chosen.append(candidate)
                        return
        first, row = options[0]
        quiet = planted.near(first.x, first.y) or refused.near(first.x, first.y)
        if quiet or len(self.rejections) >= self.params.max_rejections:
            return
        refused.add(first.x, first.y)
        self.rejections.append(self._rejection(first, batch, row))

    def optimize(self) -> SelectionReport:
        pool = self._eligible
        indices = {id(candidate): i for i, (candidate, _, _) in enumerate(pool)}
        baseline = tuple(indices[id(candidate)] for candidate in self._chosen)
        # One extra place outweighs the sum of all secondary preferences. These are
        # project preferences, not law and not a measured ecological benefit.
        base = 14 * len(pool) + 1
        problem = SelectionProblem(
            xy=tuple((c.x, c.y) for c, _, _ in pool),
            stations=tuple(f"{c.mode}:{c.station}" for c, _, _ in pool),
            weights=tuple(
                base
                + 8 * (batch.verdict(row) is Verdict.ALLOWED)
                + 4 * (not batch.needs_barrier(row))
                + 2 * (c.mode == MODE_ALLEY)
                for c, batch, row in pool
            ),
            min_gap_m=max(
                self.params.spacing_m * _SPACING_TOLERANCE, 2 * self.params.footprint_radius_m
            ),
            objective_description=(
                "First maximize eligible places; then sum preferences: allowed=8, "
                "no root barrier=4, alley=2. Species feasibility and aesthetic quality "
                "are not part of this objective."
            ),
        )
        report = select_candidates(
            problem,
            baseline,
            time_limit_s=self.params.placement_time_limit_s,
            max_candidates=self.params.placement_max_candidates,
            max_conflicts=self.params.placement_max_conflicts,
        )
        self.placements = [
            replace(self._placement(*pool[i]), number=number)
            for number, i in enumerate(report.selected, 1)
        ]
        occupied = _Grid(problem.min_gap_m)
        for placement in self.placements:
            occupied.add(placement.x, placement.y)
        self.rejections = [r for r in self.rejections if not occupied.near(r.x, r.y)]
        return report

    def _placement(self, candidate: _Candidate, batch: EvaluationBatch, row: int) -> Placement:
        return Placement(
            placement_id=_stable_id("p", self.params, candidate),
            number=len(self.placements) + 1,
            planting_type=self.params.planting_type,
            species=self.species,
            x=round(candidate.x, 3),
            y=round(candidate.y, 3),
            verdict=batch.verdict(row),
            checks=batch.checks(row),
            notes=(
                MODE_LABELS[candidate.mode],
                *((BARRIER_NOTE,) if batch.needs_barrier(row) else ()),
            ),
        )

    def _rejection(self, candidate: _Candidate, batch: EvaluationBatch, row: int) -> Rejection:
        return Rejection(
            rejection_id=_stable_id("r", self.params, candidate),
            number=len(self.rejections) + 1,
            planting_type=self.params.planting_type,
            x=round(candidate.x, 3),
            y=round(candidate.y, 3),
            verdict=batch.verdict(row),
            blocking=tuple(
                c
                for c in batch.checks(row)
                if c.outcome in {CheckOutcome.FAIL, CheckOutcome.NO_DATA}
            ),
        )


def _stable_id(prefix: str, params: PlanParams, candidate: _Candidate) -> str:
    key = f"{prefix}:{params.planting_type}:{candidate.x:.2f}:{candidate.y:.2f}"
    return f"{prefix}-{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def disabled_rules_note(rulebook: RuleBook, params: PlanParams) -> str | None:
    """Какие нормы профиль не применяет - пунктом акта. Идентификаторы - в параметрах прогона
    (disabled_rules), в строке для человека они шум."""
    if not params.disabled_rules:
        return None
    named = []
    for rule_id in sorted(params.disabled_rules):
        rule = rulebook.rule(rule_id)
        if rule is None:
            named.append(rule_id)
            continue
        # Свой пункт без связанных ссылок и пометки о сверке: в строке-сводке она повторяла
        # оговорку, которая уже стоит в тексте пункта.
        act = rulebook.label_of(rule.citation.act_id)
        named.append(f"{act}, {rule.citation.clause}")
    return "Профиль не применяет: " + "; ".join(named) + "."


def _warnings(
    features: Sequence[Feature],
    index: ConstraintIndex,
    plan_rejections: Sequence[Rejection],
    params: PlanParams,
    disabled: str | None,
) -> tuple[str, ...]:
    max_rejections = params.max_rejections
    warnings = list(index.surface.review_notes()) if index.surface is not None else []
    if disabled:
        warnings.append(disabled)
    if params.require_soil and index.surface is None:
        warnings.append(
            "Карта покрытий не построена: нет пригодных площадей или подписей покрытия. "
            "Существующее дерево само по себе не определяет грунт вокруг него. "
            "Пригодный грунт неизвестен: автоматическое размещение заблокировано."
        )
    if MODE_LAWN in params.modes and index.surface is None:
        warnings.append(
            "Заполнение газона пропущено: без карты покрытий сервис не знает, где грунт."
        )
    if MODE_ALLEY in params.modes and not any(f.object_class is ObjectClass.CURB for f in features):
        warnings.append("В чертеже не найден бортовой камень: рядовая посадка не построена.")
    if not index.has_utility_data:
        warnings.append(
            "В чертеже нет подземных сетей: отступы от сетей не проверены, "
            "посадки не допускаются или помечены 'требует согласования' (по профилю)."
        )
    if index.boundary is None:
        warnings.append(
            "Граница работ не найдена: автоматическое размещение заблокировано."
            if params.require_work_boundary
            else "Граница работ не найдена: профиль явно разрешает размещение по всему чертежу."
        )
    if len(plan_rejections) >= max_rejections:
        warnings.append(
            f"Отметок отказов больше лимита {max_rejections}: показаны только первые, "
            "остальные кандидаты отклонены без отметки в чертеже."
        )
    return tuple(warnings)
