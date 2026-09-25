"""Сборка улицы обратно: чернила чертежа против разобранной сцены.

Учёт исходов доказывает, что каждый примитив получил решение, но не что его геометрия цела.
Здесь исходник рисуется движком ezdxf (Frontend), как его показал бы CAD, и каждая
нарисованная линия проверяется шагом не длиннее допуска: есть ли в сцене объект ближе
допуска. Непокрытая длина - чернила, которые ридер не отдал расчёту.

Текст не рисуется (подписи идут отдельным каналом), штриховка - контуром, типы линий -
сплошной линией, точки - точкой. Размеры, выноски и определения атрибутов считаются
отдельно: это оформление, ридер берёт из них только текст. Ридер хранит ось полилинии с
шириной, поэтому у залитых фигур допуск шире на половину их толщины (для полосы ширины w
толщина 2S/P = w); число таких полилиний в чертеже выводится в отчёт, чтобы упрощение было
видно. Отрисовка не копится: каждая запись сразу режется и проверяется пачками, в памяти
остаются только итоги по окнам и сущностям (улица на 400 МБ не помещалась в память).
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import (
    Configuration,
    HatchPolicy,
    ImagePolicy,
    LinePolicy,
    TextPolicy,
)
from ezdxf.addons.drawing.recorder import (
    FilledPathsRecord,
    PathRecord,
    PointsRecord,
    Recorder,
    SolidLinesRecord,
)
from ezdxf.entities import Insert, LWPolyline, Polyline
from shapely import STRtree

from green.infrastructure.cad.ezdxf_fixes import install as install_ezdxf_fixes

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ezdxf.addons.drawing.properties import BackendProperties
    from ezdxf.addons.drawing.recorder import DataRecord
    from ezdxf.document import Drawing
    from ezdxf.entities import DXFGraphic
    from ezdxf.layouts import BaseLayout
    from ezdxf.npshapes import NumpyPath2d
    from numpy.typing import NDArray

    from green.domain.objects import Scene

install_ezdxf_fixes()

ANNOTATION_TYPES = frozenset(
    {
        "DIMENSION",
        "ARC_DIMENSION",
        "LARGE_RADIAL_DIMENSION",
        "LEADER",
        "MULTILEADER",
        "MLEADER",
        "ATTDEF",
        "TOLERANCE",
        "ACAD_TABLE",
    }
)
# Толщина залитой фигуры, которую ещё можно объяснить шириной полилинии вокруг оси.
_MAX_HALF_WIDTH_M = 1.0
_BATCH = 200_000

type _Key = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class InkMiss:
    """Непокрытые чернила: сущность верхнего уровня, примитив, который их нарисовал, слой."""

    handle: str
    entity_type: str
    layer: str
    missed_m: float
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class WindowScore:
    x0: float
    y0: float
    ink_m: float
    missed_m: float

    @property
    def missed_share(self) -> float:
        return self.missed_m / self.ink_m if self.ink_m else 0.0


@dataclass(frozen=True, slots=True)
class FidelityReport:
    ink_m: float
    missed_m: float
    annotation_ink_m: float
    annotation_missed_m: float
    wide_polylines: int
    windows: tuple[WindowScore, ...]
    misses: tuple[InkMiss, ...]

    @property
    def worst_window_share(self) -> float:
        return max((w.missed_share for w in self.windows), default=0.0)


def fidelity(
    doc: Drawing, scene: Scene, *, tolerance_m: float = 0.15, window_m: float = 100.0
) -> FidelityReport:
    """Сверка отрисовки исходника с геометрией сцены (до классификации, в метрах)."""
    if tolerance_m <= 0 or window_m <= 0:
        raise ValueError("Tolerance and window must be positive")
    check = _Check(doc, scene, tolerance_m, window_m)
    config = Configuration(
        text_policy=TextPolicy.IGNORE,
        hatch_policy=HatchPolicy.SHOW_OUTLINE,
        line_policy=LinePolicy.SOLID,
        image_policy=ImagePolicy.IGNORE,
        # Точка - точкой: значок $PDMODE (крест, круг размером $PDSIZE) шире допуска.
        pdmode=0,
        max_flattening_distance=check.flattening,
    )
    Frontend(RenderContext(doc), _Stream(check), config=config).draw_layout(doc.modelspace())
    return check.report(_wide_polylines(doc))


class _Stream(Recorder):
    """Recorder без записи: каждая запись сразу уходит в проверку.

    Движок сообщает о входе в каждую сущность, в том числе во вложенные в блок: по стеку
    видно, что линию рисует выноска внутри вставки (оформление), и какой примитив её дал.
    """

    def __init__(self, check: _Check) -> None:
        super().__init__()
        self._check = check
        self._stack: list[str] = []

    def enter_entity(self, entity: DXFGraphic, properties: object) -> None:  # noqa: ARG002
        self._stack.append(entity.dxftype())

    def exit_entity(self, entity: DXFGraphic) -> None:  # noqa: ARG002
        self._stack.pop()

    def store(self, record: DataRecord, properties: BackendProperties) -> None:
        self._check.add(record, properties, self._stack)


class _Check:
    def __init__(self, doc: Drawing, scene: Scene, tolerance_m: float, window_m: float) -> None:
        self.doc = doc
        self.unit = scene.unit_m
        self.tolerance = tolerance_m
        self.window = window_m
        self.flattening = 0.01 * tolerance_m / scene.unit_m
        geometries = [f.geometry for f in scene.features if not f.geometry.is_empty]
        self.tree = STRtree(geometries) if geometries else None
        self.keys: list[_Key] = []
        self.annotations: list[bool] = []
        self.xy: list[NDArray[np.float64]] = []
        self.weight: list[NDArray[np.float64]] = []
        self.extra: list[NDArray[np.float64]] = []
        self.owner: list[NDArray[np.int64]] = []
        self.pending = 0
        self.ink = self.missed = self.annotation_ink = self.annotation_missed = 0.0
        self.windows: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0.0, 0.0])
        self.lost: dict[_Key, float] = defaultdict(float)
        self.where: dict[_Key, tuple[float, float]] = {}

    def add(self, record: DataRecord, properties: BackendProperties, stack: list[str]) -> None:
        index = len(self.keys)
        primitive = stack[-1] if stack else "?"
        self.keys.append((properties.handle, primitive, properties.layer))
        self.annotations.append(any(kind in ANNOTATION_TYPES for kind in stack))
        for line, filled in _polylines(record, flattening=self.flattening):
            coords = line * self.unit
            xy, weight = _cut(coords, self.tolerance)
            self.xy.append(xy)
            self.weight.append(weight)
            self.extra.append(np.full(len(xy), _half_thickness(coords) if filled else 0.0))
            self.owner.append(np.full(len(xy), index, dtype=np.int64))
            self.pending += len(xy)
        if self.pending >= _BATCH:
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        xy = np.concatenate(self.xy)
        weight = np.concatenate(self.weight)
        owner = np.concatenate(self.owner)
        missed = ~self._covered(xy, self.tolerance + np.concatenate(self.extra))
        annotation = np.array(self.annotations, dtype=bool)[owner]
        drawing = ~annotation
        self.ink += float(weight[drawing].sum())
        self.missed += float(weight[drawing & missed].sum())
        self.annotation_ink += float(weight[annotation].sum())
        self.annotation_missed += float(weight[annotation & missed].sum())
        self._windows(xy[drawing], weight[drawing], missed[drawing])
        for position in np.flatnonzero(drawing & missed):
            key = self.keys[owner[position]]
            self.lost[key] += float(weight[position])
            self.where.setdefault(key, (float(xy[position, 0]), float(xy[position, 1])))
        self.keys, self.annotations = [], []
        self.xy, self.weight, self.extra, self.owner = [], [], [], []
        self.pending = 0

    def report(self, wide_polylines: int) -> FidelityReport:
        self.flush()
        return FidelityReport(
            ink_m=self.ink,
            missed_m=self.missed,
            annotation_ink_m=self.annotation_ink,
            annotation_missed_m=self.annotation_missed,
            wide_polylines=wide_polylines,
            windows=tuple(
                WindowScore(kx * self.window, ky * self.window, ink, missed)
                for (kx, ky), (ink, missed) in sorted(self.windows.items())
            ),
            misses=tuple(
                sorted(
                    (
                        InkMiss(h, t, layer, round(m, 3), *self.where[h, t, layer])
                        for (h, t, layer), m in self.lost.items()
                    ),
                    key=lambda miss: -miss.missed_m,
                )
            ),
        )

    def _covered(self, xy: NDArray[np.float64], reach: NDArray[np.float64]) -> NDArray:
        covered = np.zeros(len(xy), dtype=bool)
        if self.tree is None or not len(xy):
            return covered
        points = shapely.points(xy)
        (found, _), distances = self.tree.query_nearest(
            points, max_distance=float(reach.max()), return_distance=True, all_matches=False
        )
        covered[found] = distances <= reach[found]
        return covered

    def _windows(
        self, xy: NDArray[np.float64], weight: NDArray[np.float64], missed: NDArray
    ) -> None:
        if not len(xy):
            return
        cells, inverse = np.unique(
            np.floor(xy / self.window).astype(np.int64), axis=0, return_inverse=True
        )
        inverse = inverse.ravel()
        ink = np.bincount(inverse, weights=weight, minlength=len(cells))
        lost = np.bincount(inverse, weights=weight * missed, minlength=len(cells))
        for (kx, ky), i, m in zip(cells, ink, lost, strict=True):
            total = self.windows[int(kx), int(ky)]
            total[0] += float(i)
            total[1] += float(m)


def _polylines(record: DataRecord, *, flattening: float) -> Iterator[tuple[NDArray, bool]]:
    """Нарисованные линии записи в единицах чертежа; второй элемент - залитая фигура."""
    if isinstance(record, PointsRecord):
        points = record.points.np_vertices()
        if len(points) >= 3:  # noqa: PLR2004 - draw_filled_polygon
            yield np.vstack([points, points[:1]]), True
        else:
            yield points, False
    elif isinstance(record, SolidLinesRecord):
        pairs = record.lines.np_vertices().reshape(-1, 2, 2)
        yield from ((pair, False) for pair in pairs)
    elif isinstance(record, PathRecord):
        yield from ((line, False) for line in _flatten(record.path, flattening))
    elif isinstance(record, FilledPathsRecord):
        for path in record.paths:
            yield from ((line, True) for line in _flatten(path, flattening))


def _flatten(path: NumpyPath2d, distance: float) -> Iterator[NDArray[np.float64]]:
    for part in path.sub_paths():
        if part.has_curves:
            yield np.array([(v.x, v.y) for v in part.flattening(distance)], dtype=np.float64)
        else:
            yield part.np_vertices()


def _half_thickness(ring: NDArray[np.float64]) -> float:
    """Половина толщины залитой фигуры: для полосы ширины w это w/2 (2S/P)."""
    if len(ring) < 4:  # noqa: PLR2004 - closed ring
        return 0.0
    x, y = ring[:, 0], ring[:, 1]
    area = 0.5 * abs(float(np.dot(x[:-1], y[1:]) - np.dot(x[1:], y[:-1])))
    perimeter = float(np.hypot(np.diff(x), np.diff(y)).sum())
    return min(area / perimeter, _MAX_HALF_WIDTH_M) if perimeter > 0 else 0.0


def _cut(coords: NDArray, step: float) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Середины равных кусков каждого отрезка не длиннее шага; вес - длина куска."""
    if len(coords) > 1:
        start, end = coords[:-1], coords[1:]
        lengths = np.hypot(*(end - start).T)
        keep = lengths > 0
        if keep.any():
            start, end, lengths = start[keep], end[keep], lengths[keep]
            counts = np.maximum(np.ceil(lengths / step).astype(np.int64), 1)
            segment = np.repeat(np.arange(len(lengths)), counts)
            offsets = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
            t = (offsets + 0.5) / counts[segment]
            return start[segment] + (end - start)[segment] * t[:, None], (lengths / counts)[segment]
    return coords[:1].astype(np.float64), np.zeros(min(len(coords), 1))


def _wide_polylines(doc: Drawing) -> int:
    """Полилинии с шириной в пространстве модели и в блоках его вставок (стрелки размеров -
    оформление, они не считаются)."""
    seen: set[str] = set()
    pending: list[BaseLayout] = [doc.modelspace()]
    count = 0
    while pending:
        layout = pending.pop()
        for entity in layout:
            if isinstance(entity, (LWPolyline, Polyline)) and _has_width(entity):
                count += 1
            elif isinstance(entity, Insert):
                name = entity.dxf.get("name", "")
                block = doc.blocks.get(name)
                if block is not None and name not in seen:
                    seen.add(name)
                    pending.append(block)
    return count


def _has_width(entity: LWPolyline | Polyline) -> bool:
    dxf = entity.dxf
    if isinstance(entity, LWPolyline):
        widths = [dxf.get("const_width", 0.0)]
        widths += [w for _, _, s, e, _ in entity.get_points("xyseb") for w in (s, e)]
    else:
        widths = [dxf.get("default_start_width", 0.0), dxf.get("default_end_width", 0.0)]
        widths += [
            w
            for vertex in entity.vertices
            for w in (vertex.dxf.get("start_width", 0.0), vertex.dxf.get("end_width", 0.0))
        ]
    return any(math.isfinite(w) and w > 0 for w in widths)
