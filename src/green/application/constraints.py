"""Проверка нормативных отступов для пачки точек: расстояния и вердикты считаются векторно."""

from __future__ import annotations

import copy
import hashlib
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely import STRtree

from green.application.approximation import error_bound, inner_area, outer_area, reserved_buffer
from green.application.places import forget_places
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
# Допуск сравнения с нормой: 1 мм. Генератор ставит дерево ровно на норму (2,000 м от борта),
# после записи в DXF и чтения обратно координата отличается на доли микрона, и допуск 1e-6
# превращал такую посадку в нарушение при нормоконтроле собственного плана.
_EPS_M = 1e-3
_OUTCOMES = (CheckOutcome.PASS, CheckOutcome.FAIL, CheckOutcome.NO_DATA, CheckOutcome.BARRIER)
VERDICT_ORDER = (Verdict.ALLOWED, Verdict.NEEDS_APPROVAL, Verdict.FORBIDDEN, Verdict.UNKNOWN)
_VERDICTS = VERDICT_ORDER


@dataclass(frozen=True, slots=True)
class _ClassIndex:
    tree: STRtree
    features: tuple[Feature, ...]
    half_diameters: NDArray[np.float64]
    geometry_errors: NDArray[np.float64]


@dataclass(slots=True)
class _Drawing:
    """Часть индекса, которая зависит только от чертежа: объекты по классам, деревья поиска,
    твёрдые покрытия и граница работ; плюс память проверок точек.

    Одна на чертёж: портфель из восьми вариантов и этапы кустарника строили её 34 раза на
    вариант (профиль Кустанайской, 26.09.2026), а варианты проверяли одни и те же станции
    аллеи, сетку добора, зоны и ось изгороди заново.
    """

    features: Sequence[Feature]
    by_class: dict[ObjectClass, list[Feature]]
    indexes: dict[ObjectClass, _ClassIndex]
    hard: STRtree | None
    boundary: BaseGeometry | None
    has_utility_data: bool
    memo: OrderedDict[tuple[object, ...], object] = field(default_factory=OrderedDict)
    memo_cells: int = 0


# Чертежей в памяти процесса - не больше двух (сервер ведёт прогоны по одному-два); прогон в
# конце забывает их (forget_drawings), чтобы сервис не держал подоснову после работы.
_DRAWINGS: OrderedDict[int, _Drawing] = OrderedDict()
_DRAWINGS_LOCK = threading.Lock()
_DRAWINGS_KEPT = 2
# Предел памяти проверок на чертёж: правил x точек во всех запомненных пачках (около 350 МБ).
_MEMO_CELLS = 20_000_000


def _drawing(features: Sequence[Feature]) -> _Drawing:
    key = id(features)
    with _DRAWINGS_LOCK:
        cached = _DRAWINGS.get(key)
        if cached is not None and cached.features is features:
            _DRAWINGS.move_to_end(key)
            return cached
    drawing = _build_drawing(features)
    with _DRAWINGS_LOCK:
        _DRAWINGS[key] = drawing
        _DRAWINGS.move_to_end(key)
        while len(_DRAWINGS) > _DRAWINGS_KEPT:
            _DRAWINGS.popitem(last=False)
    return drawing


def _build_drawing(features: Sequence[Feature]) -> _Drawing:
    by_class: dict[ObjectClass, list[Feature]] = defaultdict(list)
    for feature in features:
        error_bound(feature)
        by_class[feature.object_class].append(feature)
    hard = [
        outer_area(f)
        for f in features
        if f.object_class.is_hard_surface and f.geometry.geom_type in _AREA_TYPES
    ]
    boundary = _boundary(by_class.get(ObjectClass.WORK_BOUNDARY, []))
    if boundary is not None:
        shapely.prepare(boundary)
    return _Drawing(
        features=features,
        by_class=by_class,
        indexes={},
        hard=STRtree(hard) if hard else None,
        boundary=boundary,
        # Линии, предположенные «сетями неизвестного типа», не считаются данными
        # о сетях: иначе нераспознанный слой скрывал бы отсутствие выгрузки коммуникаций.
        has_utility_data=any(
            cls.is_utility and cls is not ObjectClass.UTILITY_UNKNOWN for cls in by_class
        ),
    )


def forget_drawings() -> None:
    """Забыть индексы чертежей и память проверок: прогон закончен."""
    with _DRAWINGS_LOCK:
        _DRAWINGS.clear()
    forget_places()


def _points_key(points: NDArray[np.object_]) -> tuple[int, bytes]:
    coords = shapely.get_coordinates(points)
    return len(points), hashlib.blake2b(coords.tobytes(), digest_size=16).digest()


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

    def slack(self) -> NDArray[np.float64]:
        """Запас до самой тесной нормы до подземной сети в каждой точке, м: измерено минус норма.

        Только сети: их положение на плане 1:500 расходится с натурой до 0,5 м (СП
        317.1325800.2017, п. 5.3.5.3), а борт и стену при посадке меряют от настоящих. Считаются
        только измеренные расстояния: «сетей в чертеже нет» - не запас. Точка, где не измерено
        ничего, получает минус бесконечность.
        """
        thresholds = np.array([r.min_distance_m for r in self.rules], dtype=np.float64)[:, None]
        if not len(self.rules):
            return np.full(len(self), -np.inf)
        hidden = np.array([r.object_class.is_utility for r in self.rules], dtype=bool)[:, None]
        measured = (self.nearest >= 0) & (self.outcomes != _NO_DATA) & (thresholds > 0) & hidden
        worst = np.where(measured, self.clearance - thresholds, np.inf).min(axis=0)
        return np.where(np.isfinite(worst), worst, -np.inf)

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

    def __init__(  # noqa: PLR0913 - named policies distinguish missing evidence from permission
        self,
        features: Sequence[Feature],
        rules: Sequence[DistanceRule],
        *,
        require_utility_data: bool,
        surface: SurfaceMap | None = None,
        barrier_distance_m: float | None = None,
        require_soil: bool = False,
        require_work_boundary: bool = False,
        planting_radius_m: float = 0.0,
    ) -> None:
        self.surface = surface
        self._require_soil = require_soil
        self._require_work_boundary = require_work_boundary
        if not np.isfinite(planting_radius_m) or planting_radius_m < 0:
            raise ValueError("Planting radius must be finite and non-negative")
        self._planting_radius_m = planting_radius_m
        drawing = _drawing(features)
        self._drawing = drawing
        self._by_class = drawing.by_class
        self._indexes = drawing.indexes
        self._require_utility_data = require_utility_data
        self.configure(rules, barrier_distance_m)
        self.has_utility_data = drawing.has_utility_data
        self._hard = drawing.hard
        self.has_surface_polygons = drawing.hard is not None
        self.boundary: BaseGeometry | None = drawing.boundary

    def configure(
        self, rules: Sequence[DistanceRule], barrier_distance_m: float | None = None
    ) -> None:
        """Задать набор правил; индекс класса строится один раз и запоминается.

        barrier_distance_m - наименьшее расстояние до сетей и бордюров, допустимое с
        прикорневым барьером; None - барьеры не рассматриваются, действует табличная норма.
        """
        self._barrier_distance_m = barrier_distance_m
        self._rules = tuple(rules)
        self._rules_key = tuple(
            (r.rule_id, r.object_class, r.planting_type, r.min_distance_m, r.measure_to, r.severity)
            for r in self._rules
        )
        self._forbid = np.array([r.severity is Severity.FORBID for r in self._rules], dtype=bool)
        for cls in {rule.object_class for rule in self._rules} - self._indexes.keys():
            if self._by_class.get(cls):
                self._indexes[cls] = _index(tuple(self._by_class[cls]))

    def with_rules(
        self, rules: Sequence[DistanceRule], *, barrier_distance_m: float | None = None
    ) -> ConstraintIndex:
        """Тот же чертёж с другим набором правил: деревья поиска по классам общие.

        Нужен, когда точки проверяются правилами конкретной посадки (её вид, крона, род), а
        объекты подосновы те же: на генплане в сотни тысяч объектов индекс класса строится
        секунды, и повторять это на каждый вид незачем. Требования к грунту, границе работ и
        радиусу посадочного места - те же, что у исходного индекса.
        """
        clone = copy.copy(self)
        clone.configure(rules, barrier_distance_m)
        return clone

    def plantable(self, points: NDArray[np.object_], *, margin_m: float = 0.0) -> NDArray[np.bool_]:
        """Посадочное место целиком на грунте, вне покрытий и внутри границы работ."""
        key = (
            "plantable",
            self._planting_radius_m + margin_m,
            self._require_soil,
            self._require_work_boundary,
            id(self.surface),
            *_points_key(points),
        )
        cached = self._recall(key)
        if isinstance(cached, np.ndarray):
            return cached.copy()
        mask = self._plantable(points, margin_m)
        self._remember(key, mask.copy(), len(points))
        return mask

    def _plantable(self, points: NDArray[np.object_], margin_m: float) -> NDArray[np.bool_]:
        mask = np.ones(len(points), dtype=bool)
        radius = self._planting_radius_m + margin_m
        if (self._require_soil and self.surface is None) or (
            self._require_work_boundary and self.boundary is None
        ):
            return np.zeros(len(points), dtype=bool)
        if self._hard is not None and len(points):
            inside = self._hard.query(points, predicate="intersects")
            mask[np.unique(inside[0])] = False
            if radius > 0:
                near = self._hard.query(points, predicate="dwithin", distance=radius)
                mask[np.unique(near[0])] = False
        if self.boundary is not None and len(points):
            mask &= shapely.contains(self.boundary, points)
            if radius > 0:
                mask &= shapely.distance(points, self.boundary.boundary) >= radius
        if self.surface is not None and len(points):
            mask &= self.surface.fits_soil(points, radius)
        return mask

    def evaluate(self, points: NDArray[np.object_], *, margin_m: float = 0.0) -> EvaluationBatch:
        """Все правила для пачки точек. Та же пачка при тех же правилах берётся из памяти
        чертежа: варианты портфеля проверяют одни и те же станции, результат тот же."""
        key = (
            "evaluate",
            self._rules_key,
            self._barrier_distance_m,
            self._require_utility_data,
            margin_m,
            *_points_key(points),
        )
        cached = self._recall(key)
        if isinstance(cached, EvaluationBatch):
            return cached
        batch = self._evaluate(points, margin_m)
        for array in (batch.outcomes, batch.clearance, batch.nearest, batch.verdict_codes):
            array.flags.writeable = False
        self._remember(key, batch, len(points) * max(len(self._rules), 1))
        return batch

    def _recall(self, key: tuple[object, ...]) -> object | None:
        memo = self._drawing.memo
        with _DRAWINGS_LOCK:
            value = memo.get(key)
            if value is not None:
                memo.move_to_end(key)
        return value

    def _remember(self, key: tuple[object, ...], value: object, cells: int) -> None:
        drawing = self._drawing
        with _DRAWINGS_LOCK:
            if key in drawing.memo:
                return
            drawing.memo[key] = value
            drawing.memo_cells += cells
            while drawing.memo_cells > _MEMO_CELLS and len(drawing.memo) > 1:
                _, old = drawing.memo.popitem(last=False)
                drawing.memo_cells -= _cells(old)

    def _evaluate(self, points: NDArray[np.object_], margin_m: float) -> EvaluationBatch:
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
            values, owners = _nearest_clearance(index, points, rule.measure_to)
            clearance[row] = values
            nearest[row] = owners
            # Допуск на округление: кандидат, поставленный ровно на норму, её не нарушает.
            outcomes[row] = np.where(
                values >= rule.min_distance_m + margin_m - _EPS_M, _PASS, _FAIL
            )
            if self._relaxable(rule):
                relaxed = (outcomes[row] == _FAIL) & (
                    values >= (self._barrier_distance_m or 0.0) + margin_m - _EPS_M
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


# Граница работ, чьи концы разошлись не больше чем на 5 м и на 1% длины, замыкается хордой:
# это погрешность черчения, а не другой контур (Нижние Поля: «Граница Заказа» 4,9 км с разрывом
# 3,4 м). Шире - граница не достраивается, прогон пишет, что границы нет.
_BOUNDARY_GAP_M = 5.0
_BOUNDARY_GAP_SHARE = 0.01


def work_boundary(features: Sequence[Feature]) -> BaseGeometry | None:
    """Граница работ чертежа - та же, что ограничивает размещение посадок."""
    return _boundary([f for f in features if f.object_class is ObjectClass.WORK_BOUNDARY])


def boundary_gaps(features: Sequence[Feature]) -> list[tuple[str, float]]:
    """Слои и разрывы, м, линий границы работ, которые граница замкнула хордой."""
    return [
        (f.layer, gap)
        for f in features
        if f.object_class is ObjectClass.WORK_BOUNDARY
        for part in shapely.get_parts(f.geometry)
        if (gap := _bridgeable_gap(part)) is not None
    ]


def _bridgeable_gap(line: BaseGeometry) -> float | None:
    if line.geom_type != "LineString" or line.is_ring or len(line.coords) < 3:  # noqa: PLR2004 - loop needs three vertices
        return None
    first, last = line.coords[0], line.coords[-1]
    gap = float(shapely.Point(first).distance(shapely.Point(last)))
    if 0 < gap <= min(_BOUNDARY_GAP_M, _BOUNDARY_GAP_SHARE * line.length):
        return gap
    return None


def _closed(line: BaseGeometry) -> BaseGeometry:
    parts = [
        shapely.LineString([*part.coords, part.coords[0]])
        if _bridgeable_gap(part) is not None
        else part
        for part in shapely.get_parts(line)
    ]
    return parts[0] if len(parts) == 1 else shapely.MultiLineString(parts)


def _boundary(features: Sequence[Feature]) -> BaseGeometry | None:
    """Граница работ из полигонов или из замкнутых линий (как «Граница заказа» Геотреста)."""
    areas = [inner_area(f) for f in features if f.geometry.geom_type in _AREA_TYPES]
    line_features = [f for f in features if f.geometry.geom_type in _LINE_TYPES]
    lines = [_closed(f.geometry) for f in line_features]
    if lines:
        reserve = max(error_bound(f) for f in line_features)
        areas.extend(
            reserved_buffer(area, -reserve)
            for area in shapely.get_parts(shapely.polygonize([shapely.union_all(lines)]))
        )
    if not areas:
        return None
    merged = shapely.union_all(areas)
    return None if merged.is_empty else merged


def _cells(value: object) -> int:
    if isinstance(value, EvaluationBatch):
        return int(value.outcomes.size) or len(value)
    return len(value) if isinstance(value, np.ndarray) else 0


def _index(features: tuple[Feature, ...]) -> _ClassIndex:
    halves = np.array([(f.diameter_m or 0.0) / 2 for f in features], dtype=np.float64)
    errors = np.array([f.geometry_error_m for f in features], dtype=np.float64)
    if not np.isfinite(errors).all() or (errors < 0).any():
        raise ValueError("Unbounded or invalid input geometry error")
    return _ClassIndex(STRtree([occupied_geometry(f) for f in features]), features, halves, errors)


# Полуширина самого широкого сооружения сети, которое рисуют площадью (тепловая камера,
# канал): шире - не сооружение. Параметр проекта.
_NETWORK_STRUCTURE_M = 10.0


def _inradius(geometry: BaseGeometry) -> float:
    """Радиус наибольшего вписанного круга (с точностью 0,5 м) по всем частям фигуры."""
    return max(
        float(shapely.length(shapely.maximum_inscribed_circle(part, 0.5)))
        for part in shapely.get_parts(geometry)
    )


def occupied_geometry(feature: Feature) -> BaseGeometry:
    """Место, которое объект занимает на земле: у замкнутого контура - вместе с площадью.

    Площадная фигура сети занимает свою площадь, пока она не шире сооружения сети: камера,
    канал, колодец. Фигура, в которую вписывается круг радиусом больше 10 м, - зона действия
    или петля линии, а не сооружение: она мерится по контуру, иначе любая точка внутри
    оказалась бы «на кабеле» (Харьковский проезд: окружности радиусом 150 м на слое «ЭН_ЗУ»).
    """
    geometry = feature.geometry
    if (
        feature.object_class.is_utility
        and geometry.geom_type in {"Polygon", "MultiPolygon"}
        and _inradius(geometry) > _NETWORK_STRUCTURE_M
    ):
        return geometry.boundary
    if not (
        feature.object_class.occupies_interior
        and geometry.geom_type == "LineString"
        and geometry.is_closed
    ):
        return geometry
    area = shapely.make_valid(shapely.Polygon(geometry.coords))
    return area if area.area > 0 else geometry


def _nearest_clearance(
    index: _ClassIndex, points: NDArray[np.object_], measure: MeasureTo
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Nearest wall is not necessarily the wall of the nearest axis.

    The nearest axis supplies an upper bound b on the signed wall distance.
    A better object must have distance <= b + maximum reserved distance. Query that
    bounded neighbourhood, then minimise distance minus radius/error. No polygonal
    circle buffers or all-pairs matrix. Batches bound temporary query memory.
    """
    pairs, distances = index.tree.query_nearest(points, return_distance=True, all_matches=False)
    values = np.empty(len(points))
    owners = np.empty(len(points), dtype=np.int64)
    values[pairs[0]] = distances
    owners[pairs[0]] = pairs[1]
    reserve = index.geometry_errors.copy()
    if measure is MeasureTo.OUTER_WALL:
        reserve += index.half_diameters
    values -= reserve[owners]
    maximum_radius = float(reserve.max())
    if maximum_radius > float(reserve.min()):
        batch_size = 4096
        for start in range(0, len(points), batch_size):
            end = min(start + batch_size, len(points))
            subset = points[start:end]
            radius = np.maximum(values[start:end] + maximum_radius, 0) + 1e-9
            point_ids, feature_ids = index.tree.query(subset, predicate="dwithin", distance=radius)
            clearance = (
                shapely.distance(subset[point_ids], index.tree.geometries[feature_ids])
                - reserve[feature_ids]
            )
            best = np.full(len(subset), np.inf)
            np.minimum.at(best, point_ids, clearance)
            winners = clearance == best[point_ids]
            winner_ids = np.full(len(subset), len(index.features), dtype=np.int64)
            np.minimum.at(winner_ids, point_ids[winners], feature_ids[winners])
            values[start:end] = best
            owners[start:end] = winner_ids
    np.maximum(values, 0.0, out=values)
    return values, owners
