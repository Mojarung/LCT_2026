"""Стратегии размещения. По умолчанию: рядовая посадка вдоль бортового камня."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

import numpy as np
import shapely

from green.application.constraints import ConstraintIndex, EvaluationBatch
from green.application.errors import InputError
from green.application.surfaces import build_surface_map
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Placement, Plan, Rejection, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry import LineString

    from green.application.params import PlanParams
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Species

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


@dataclass(frozen=True, slots=True)
class _Candidate:
    station: int
    offset_m: float
    x: float
    y: float


class CurbAlleyStrategy:
    """Жадная аллея вдоль борта: на каждой станции первый допустимый отступ, шаг по сетке.

    Борт в данных бывает сплошной линией (АСУ ОДХ) или тысячами штрихов по 0.7 м
    (топоплан Геотреста), поэтому станции строятся и по длинным линиям, и по коротким
    фрагментам, а шаг аллеи обеспечивает отбор. Результат детерминирован.
    """

    def plan(
        self,
        features: Sequence[Feature],
        labels: Sequence[TextLabel],
        rulebook: RuleBook,
        species: Species,
        params: PlanParams,
    ) -> Plan:
        ban = rulebook.ban_for(species.name_lat)
        if ban is not None:
            raise InputError(f"Вид {species.name_lat} запрещён правилом {ban.rule_id}")

        rules = rulebook.distance_rules_for(params.planting_type, species.name_lat)
        index = ConstraintIndex(features, rules, require_utility_data=params.require_utility_data)
        if params.require_soil:
            index.surface = build_surface_map(
                features, labels, index.boundary, params.surface_cell_m
            )
        candidates = _candidates(_curb_lines(features), params)
        points = shapely.points([(c.x, c.y) for c in candidates]) if candidates else np.array([])
        positions = np.flatnonzero(index.plantable(points))
        selector = _Selector(species=species, params=params)
        if len(positions):
            selector.batch = index.evaluate(points[positions])
            for row, position in enumerate(positions.tolist()):
                selector.offer(candidates[position], row)
        selector.flush()
        stats: dict[str, int | float] = {
            "candidates": len(candidates),
            "candidates_plantable": len(positions),
        }
        if index.surface is not None:
            stats.update({f"surface_{k}": v for k, v in index.surface.summary().items()})
        return Plan(
            placements=tuple(selector.placements),
            rejections=tuple(selector.rejections),
            warnings=_warnings(features, index, selector.rejections, params),
            stats=stats,
        )


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


def _candidates(lines: list[LineString], params: PlanParams) -> list[_Candidate]:
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
                    candidates.append(_Candidate(station, offset, float(x), float(y)))
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
    """Обходит станции по порядку: принимает первый допустимый отступ, дедуплицирует отказы."""

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
        gap = self.params.spacing_m * _SPACING_TOLERANCE
        planted = self._planted = self._planted or _Grid(gap)
        refused = self._refused = self._refused or _Grid(gap)
        ranks = [Verdict.ALLOWED]
        if self.params.allow_needs_approval:
            ranks.append(Verdict.NEEDS_APPROVAL)

        # Сначала любой отступ без замечаний, и только потом отступ с согласованием.
        for verdict in ranks:
            for candidate, row in options:
                if batch.verdict(row) is verdict:
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
        )

    def _rejection(self, candidate: _Candidate, batch: EvaluationBatch, row: int) -> Rejection:
        return Rejection(
            rejection_id=_stable_id("r", self.params, candidate),
            number=len(self.rejections) + 1,
            planting_type=self.params.planting_type,
            x=round(candidate.x, 3),
            y=round(candidate.y, 3),
            verdict=batch.verdict(row),
            blocking=tuple(c for c in batch.checks(row) if c.outcome is not CheckOutcome.PASS),
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
    if params.require_soil and index.surface is None and not index.has_surface_polygons:
        warnings.append(
            "Карта покрытий не построена: в чертеже нет подписей материала покрытий "
            "(«А», «Ц», «ПЛ») или признаков грунта («ГАЗОН», существующие деревья). "
            "Сторона борта (проезжая часть или тротуар) не различается."
        )
    if not any(f.object_class is ObjectClass.CURB for f in features):
        warnings.append("В чертеже не найден бортовой камень: рядовая посадка не построена.")
    if not index.has_utility_data:
        warnings.append(
            "В чертеже нет подземных сетей: отступы от сетей не проверены, "
            "посадки не допускаются или помечены 'требует согласования' (по профилю)."
        )
    if index.boundary is None:
        warnings.append("Граница работ не найдена: размещение по всему чертежу.")
    if len(plan_rejections) >= max_rejections:
        warnings.append(
            f"Отметок отказов больше лимита {max_rejections}: показаны только первые, "
            "остальные кандидаты отклонены без отметки в чертеже."
        )
    return tuple(warnings)
