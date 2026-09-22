"""Стратегия размещения: жадный отбор кандидатов двух приёмов по одним и тем же правилам.

Приём «alley»: рядовая посадка вдоль бортового камня, станции по линиям и штрихам борта,
отступы из профиля с обеих сторон. Приём «lawn»: заполнение грунта шахматной сеткой с шагом
посадки по карте покрытий, как сажают проектировщики во дворах. Оба приёма проверяются
одним ConstraintIndex, посадки держат шаг между собой. Результат детерминирован.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol

import numpy as np
import shapely

from green.application.barriers import BARRIER_NOTE, NEAR_M, barrier_distance
from green.application.constraints import ConstraintIndex, EvaluationBatch
from green.application.errors import InputError
from green.application.params import active_distance_rules, species_distance_rules
from green.application.species_norms import species_norms
from green.application.surfaces import Material, build_surface_map
from green.application.zones import build_zones
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Placement, Plan, Rejection, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry import LineString

    from green.application.params import PlanParams
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Species

MODE_ALLEY = "alley"
MODE_LAWN = "lawn"
MODE_SHRUB_GROUP = "shrub_group"
MODE_LABELS = {
    MODE_ALLEY: "аллея вдоль борта",
    MODE_LAWN: "заполнение газона",
    MODE_SHRUB_GROUP: "группа кустарников на месте дерева",
}
_TANGENT_STEP_M = 0.5
_SPACING_TOLERANCE = 0.95
_Z_ORDER_BITS = 16


class PlacementStrategy(Protocol):
    def plan(
        self,
        features: Sequence[Feature],
        labels: Sequence[TextLabel],
        rulebook: RuleBook,
        species: Species,
        params: PlanParams,
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
    ) -> tuple[Placement, ...]: ...


@dataclass(frozen=True, slots=True)
class _Candidate:
    station: int
    mode: str
    x: float
    y: float


class GreedyPlantingStrategy:
    """Аллея вдоль борта, затем заполнение газона; первый допустимый вариант на станции."""

    def plan(
        self,
        features: Sequence[Feature],
        labels: Sequence[TextLabel],
        rulebook: RuleBook,
        species: Species,
        params: PlanParams,
    ) -> Plan:
        # В режиме одного вида видовые нормы проверяются здесь; в режиме подбора - на каждой
        # паре «посадка - вид» (assortment.filters), а вид профиля лишь задаёт отступы по роду.
        single = params.assortment_mode == "single"
        if single:
            norms = species_norms(species, rulebook, params.territory, params.planting_category)
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
            index.surface = build_surface_map(
                features,
                labels,
                index.boundary,
                params.surface_cell_m,
                max_distance_m=params.surface_max_distance_m,
                ambiguity_m=params.surface_ambiguity_m,
                tree_distance_m=params.tree_seed_distance_m,
            )
        selector = _Selector(species=species, params=params)
        stats: dict[str, int | float] = {}
        if MODE_ALLEY in params.modes:
            candidates = _curb_candidates(_curb_lines(features), params)
            stats["alley_candidates"] = len(candidates)
            stats["alley_plantable"] = _offer(index, selector, candidates)
        if MODE_LAWN in params.modes and index.surface is not None:
            candidates = _lawn_candidates(index.surface, params)
            stats["lawn_candidates"] = len(candidates)
            stats["lawn_plantable"] = _offer(index, selector, candidates)
        if index.surface is not None:
            stats.update({f"surface_{k}": v for k, v in index.surface.summary().items()})
        zones = build_zones(index, params.zone_cell_m) if params.zones else ()
        for zone in zones:
            stats[f"zone_{zone.verdict.value}_m2"] = round(zone.area_m2)
        return Plan(
            placements=tuple(selector.placements),
            rejections=tuple(selector.rejections),
            warnings=_warnings(features, index, selector.rejections, params),
            stats=stats,
            zones=zones,
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
            index.surface = build_surface_map(
                features,
                labels,
                index.boundary,
                params.surface_cell_m,
                max_distance_m=params.surface_max_distance_m,
                ambiguity_m=params.surface_ambiguity_m,
                tree_distance_m=params.tree_seed_distance_m,
            )
        size = params.shrub_group_size
        offsets = [(i - (size - 1) / 2) * params.spacing_m for i in range(size)]
        candidates = [
            _Candidate(station, MODE_SHRUB_GROUP, round(cx + dx, 3), round(cy + dy, 3))
            for station, (cx, cy) in enumerate(centers)
            for dx in offsets
            for dy in offsets
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


def _curb_lines(features: Sequence[Feature]) -> list[LineString]:
    parts = []
    for feature in features:
        if feature.object_class is not ObjectClass.CURB:
            continue
        geometry = feature.geometry
        if geometry.geom_type in {"Polygon", "MultiPolygon"}:
            geometry = geometry.boundary
        parts.extend(p for p in shapely.get_parts(geometry) if p.geom_type == "LineString")
    if not parts:
        return []
    merged = shapely.line_merge(shapely.union_all(parts))
    lines = [line for line in shapely.get_parts(merged) if line.length > 0]
    centroids = shapely.get_coordinates(shapely.centroid(lines))
    order = np.argsort(_z_order(centroids), kind="stable")
    return [lines[i] for i in order]


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

    def offer(self, candidate: _Candidate, row: int) -> None:
        if candidate.station != self._station:
            self.flush()
            self._station = candidate.station
        self._options.append((candidate, row))

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
                        return
        first, row = options[0]
        quiet = planted.near(first.x, first.y) or refused.near(first.x, first.y)
        if quiet or len(self.rejections) >= self.params.max_rejections:
            return
        refused.add(first.x, first.y)
        self.rejections.append(self._rejection(first, batch, row))

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


def _warnings(
    features: Sequence[Feature],
    index: ConstraintIndex,
    plan_rejections: Sequence[Rejection],
    params: PlanParams,
) -> tuple[str, ...]:
    max_rejections = params.max_rejections
    warnings = []
    if params.disabled_rules:
        warnings.append(
            "Профиль отключает правила: " + ", ".join(sorted(params.disabled_rules)) + "."
        )
    if params.require_soil and index.surface is None:
        warnings.append(
            "Карта покрытий не построена: в чертеже нет подписей материала покрытий "
            "(«А», «Ц», «ПЛ») или признаков грунта («ГАЗОН», существующие деревья). "
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
