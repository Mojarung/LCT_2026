"""Проверка нормативных отступов для пачки точек: расстояния и вердикты считаются векторно."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely import STRtree

from green.application.surfaces import Material
from green.domain.norms import MeasureTo, PlantingType, Severity
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, RuleCheck, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.application.surfaces import SurfaceMap
    from green.domain.norms import DistanceRule
    from green.domain.objects import Feature

_AREA_TYPES = frozenset({"Polygon", "MultiPolygon"})
_LINE_TYPES = frozenset({"LineString", "MultiLineString"})
_PASS, _FAIL, _NO_DATA, _BARRIER = 0, 1, 2, 3
_EPS_M = 1e-6
_OUTCOMES = (CheckOutcome.PASS, CheckOutcome.FAIL, CheckOutcome.NO_DATA, CheckOutcome.BARRIER)
VERDICT_ORDER = (Verdict.ALLOWED, Verdict.NEEDS_APPROVAL, Verdict.FORBIDDEN, Verdict.UNKNOWN)
_VERDICTS = VERDICT_ORDER


@dataclass(frozen=True, slots=True)
class _ClassIndex:
    tree: STRtree
    features: tuple[Feature, ...]
    half_diameters: NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class EvaluationBatch:
    """Результат проверки всех правил для пачки точек. RuleCheck строятся только по запросу."""

    rules: tuple[DistanceRule, ...]
    outcomes: NDArray[np.int8]
    clearance: NDArray[np.float64]
    nearest: NDArray[np.int64]
    features: tuple[tuple[Feature, ...], ...]
    verdict_codes: NDArray[np.int8]

    def __len__(self) -> int:
        return len(self.verdict_codes)

    def verdict(self, position: int) -> Verdict:
        return _VERDICTS[int(self.verdict_codes[position])]

    def needs_barrier(self, position: int) -> bool:
        """Точка допустима только с прикорневым барьером хотя бы у одного объекта."""
        return bool((self.outcomes[:, position] == _BARRIER).any())

    def checks(self, position: int) -> tuple[RuleCheck, ...]:
        result = []
        for row, rule in enumerate(self.rules):
            feature_pos = int(self.nearest[row, position])
            located = feature_pos >= 0
            result.append(
                RuleCheck(
                    rule_id=rule.rule_id,
                    outcome=_OUTCOMES[int(self.outcomes[row, position])],
                    threshold_m=rule.min_distance_m,
                    measured_m=round(float(self.clearance[row, position]), 3) if located else None,
                    nearest=self.features[row][feature_pos].ref if located else None,
                    object_class=rule.object_class,
                )
            )
        return tuple(result)


class ConstraintIndex:
    """Индекс объектов подосновы по классам и правила, которые к ним применяются."""

    def __init__(
        self,
        features: Sequence[Feature],
        rules: Sequence[DistanceRule],
        *,
        require_utility_data: bool,
        surface: SurfaceMap | None = None,
        barrier_distance_m: float | None = None,
    ) -> None:
        self.surface = surface
        # Наименьшее расстояние до сетей и бордюров, допустимое с прикорневым барьером; None -
        # барьеры не рассматриваются, действует только табличная норма.
        self._barrier_distance_m = barrier_distance_m
        by_class: dict[ObjectClass, list[Feature]] = defaultdict(list)
        for feature in features:
            by_class[feature.object_class].append(feature)

        self._rules = tuple(rules)
        self._forbid = np.array([r.severity is Severity.FORBID for r in self._rules], dtype=bool)
        self._require_utility_data = require_utility_data
        # Линии, дополненные до «сети неизвестного типа» (fail-closed), не считаются данными
        # о сетях: иначе нераспознанный слой скрывал бы отсутствие выгрузки коммуникаций.
        self.has_utility_data = any(
            cls.is_utility and cls is not ObjectClass.UTILITY_UNKNOWN for cls in by_class
        )
        self._indexes = {
            cls: _index(tuple(by_class[cls]))
            for cls in {rule.object_class for rule in self._rules}
            if by_class.get(cls)
        }
        hard = [
            f.geometry
            for f in features
            if f.object_class.is_hard_surface and f.geometry.geom_type in _AREA_TYPES
        ]
        self._hard = STRtree(hard) if hard else None
        self.has_surface_polygons = bool(hard)
        self.boundary: BaseGeometry | None = _boundary(by_class.get(ObjectClass.WORK_BOUNDARY, []))
        if self.boundary is not None:
            shapely.prepare(self.boundary)

    def plantable(self, points: NDArray[np.object_]) -> NDArray[np.bool_]:
        """Точка на грунте по карте покрытий, не на твёрдом покрытии и внутри границы работ."""
        mask = np.ones(len(points), dtype=bool)
        if self._hard is not None and len(points):
            inside = self._hard.query(points, predicate="within")
            mask[np.unique(inside[0])] = False
        if self.boundary is not None and len(points):
            mask &= shapely.contains(self.boundary, points)
        if self.surface is not None and len(points):
            mask &= self.surface.material(points) == Material.SOIL
        return mask

    def evaluate(self, points: NDArray[np.object_]) -> EvaluationBatch:
        count, rules = len(points), len(self._rules)
        outcomes = np.zeros((rules, count), dtype=np.int8)
        clearance = np.full((rules, count), np.nan)
        nearest = np.full((rules, count), -1, dtype=np.int64)
        features: list[tuple[Feature, ...]] = []
        for row, rule in enumerate(self._rules):
            index = self._indexes.get(rule.object_class)
            if index is None:
                features.append(())
                if rule.object_class.is_utility and not self.has_utility_data:
                    outcomes[row] = _NO_DATA
                continue
            features.append(index.features)
            if not count:
                continue
            pairs, distances = index.tree.query_nearest(
                points, return_distance=True, all_matches=False
            )
            values = np.empty(count)
            owners = np.empty(count, dtype=np.int64)
            values[pairs[0]] = distances
            owners[pairs[0]] = pairs[1]
            if rule.measure_to is MeasureTo.OUTER_WALL:
                values -= index.half_diameters[owners]
            np.maximum(values, 0.0, out=values)
            clearance[row] = values
            nearest[row] = owners
            # Допуск на округление: кандидат, поставленный ровно на норму, её не нарушает.
            outcomes[row] = np.where(values >= rule.min_distance_m - _EPS_M, _PASS, _FAIL)
            if self._relaxable(rule):
                relaxed = (outcomes[row] == _FAIL) & (
                    values >= (self._barrier_distance_m or 0.0) - _EPS_M
                )
                outcomes[row][relaxed] = _BARRIER
        return EvaluationBatch(
            rules=self._rules,
            outcomes=outcomes,
            clearance=clearance,
            nearest=nearest,
            features=tuple(features),
            verdict_codes=self._verdicts(outcomes),
        )

    def _relaxable(self, rule: DistanceRule) -> bool:
        return (
            self._barrier_distance_m is not None
            and rule.planting_type is PlantingType.TREE
            and rule.severity is Severity.FORBID
            and rule.object_class.is_barrier_relaxable
            and rule.min_distance_m > self._barrier_distance_m
        )

    def _verdicts(self, outcomes: NDArray[np.int8]) -> NDArray[np.int8]:
        failed = outcomes == _FAIL
        forbid = (failed & self._forbid[:, None]).any(axis=0)
        approval = (failed & ~self._forbid[:, None]).any(axis=0)
        no_data = (outcomes == _NO_DATA).any(axis=0)
        missing = Verdict.UNKNOWN if self._require_utility_data else Verdict.NEEDS_APPROVAL
        codes = np.select(
            [forbid, no_data, approval],
            [
                _VERDICTS.index(Verdict.FORBIDDEN),
                _VERDICTS.index(missing),
                _VERDICTS.index(Verdict.NEEDS_APPROVAL),
            ],
            default=_VERDICTS.index(Verdict.ALLOWED),
        )
        return codes.astype(np.int8)


def _boundary(features: Sequence[Feature]) -> BaseGeometry | None:
    """Граница работ из полигонов или из замкнутых линий (как «Граница заказа» Геотреста)."""
    areas = [f.geometry for f in features if f.geometry.geom_type in _AREA_TYPES]
    lines = [f.geometry for f in features if f.geometry.geom_type in _LINE_TYPES]
    if lines:
        areas.extend(shapely.get_parts(shapely.polygonize([shapely.union_all(lines)])))
    if not areas:
        return None
    merged = shapely.union_all(areas)
    return None if merged.is_empty else merged


def _index(features: tuple[Feature, ...]) -> _ClassIndex:
    halves = np.array([(f.diameter_m or 0.0) / 2 for f in features], dtype=np.float64)
    return _ClassIndex(STRtree([f.geometry for f in features]), features, halves)
