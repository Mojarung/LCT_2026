"""Сборка улицы обратно: чернила чертежа против разобранной сцены.

Учёт исходов доказывает, что каждый примитив получил решение, но не что его геометрия цела.
Здесь исходник рисуется движком ezdxf (Frontend + Recorder), как его показал бы CAD, и каждая
нарисованная линия проверяется шагом не длиннее допуска: есть ли в сцене объект ближе
допуска. Непокрытая длина - чернила, которые ридер не отдал расчёту.

Текст не рисуется (подписи идут отдельным каналом), штриховка - контуром, типы линий -
сплошной линией. Размеры, выноски и определения атрибутов считаются отдельно: это
оформление, ридер берёт из них только текст. Ридер хранит ось полилинии с шириной, поэтому у
залитых фигур допуск шире на половину их толщины (для полосы ширины w толщина 2S/P = w);
число таких полилиний в чертеже выводится в отчёт, чтобы упрощение было видно.
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

if TYPE_CHECKING:
    from collections.abc import Iterator

    from ezdxf.addons.drawing.properties import BackendProperties
    from ezdxf.addons.drawing.recorder import DataRecord
    from ezdxf.document import Drawing
    from ezdxf.layouts import BaseLayout
    from ezdxf.npshapes import NumpyPath2d
    from numpy.typing import NDArray

    from green.domain.objects import Scene

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
    }
)
# Толщина залитой фигуры, которую ещё можно объяснить шириной полилинии вокруг оси.
_MAX_HALF_WIDTH_M = 1.0
_BATCH = 200_000


@dataclass(frozen=True, slots=True)
class InkMiss:
    """Непокрытые чернила одной сущности верхнего уровня на одном слое."""

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


@dataclass(slots=True)
class _Samples:
    xy: list[NDArray[np.float64]]
    weight: list[NDArray[np.float64]]
    extra: list[NDArray[np.float64]]
    stroke: list[NDArray[np.int64]]


def fidelity(
    doc: Drawing, scene: Scene, *, tolerance_m: float = 0.15, window_m: float = 100.0
) -> FidelityReport:
    """Сверка отрисовки исходника с геометрией сцены (до классификации, в метрах)."""
    if tolerance_m <= 0 or window_m <= 0:
        raise ValueError("Tolerance and window must be positive")
    unit = scene.unit_m
    step = tolerance_m
    samples = _Samples([], [], [], [])
    strokes: list[tuple[str, str]] = []
    for record, properties in _render(doc, flattening=0.01 * tolerance_m / unit):
        for line, filled in _polylines(record, flattening=0.01 * tolerance_m / unit):
            coords = line * unit
            extra = _half_thickness(coords) if filled else 0.0
            if _sample(coords, step, extra, len(strokes), samples):
                strokes.append((properties.handle, properties.layer))
    if not strokes:
        return FidelityReport(0.0, 0.0, 0.0, 0.0, _wide_polylines(doc), (), ())
    xy = np.concatenate(samples.xy)
    weight = np.concatenate(samples.weight)
    extra = np.concatenate(samples.extra)
    stroke = np.concatenate(samples.stroke)
    covered = _covered(scene, xy, tolerance_m + extra)
    types = [_entity_type(doc, handle) for handle, _ in strokes]
    annotation = np.array([t in ANNOTATION_TYPES for t in types], dtype=bool)[stroke]
    missed = ~covered
    drawing = ~annotation
    return FidelityReport(
        ink_m=float(weight[drawing].sum()),
        missed_m=float(weight[drawing & missed].sum()),
        annotation_ink_m=float(weight[annotation].sum()),
        annotation_missed_m=float(weight[annotation & missed].sum()),
        wide_polylines=_wide_polylines(doc),
        windows=_windows(xy[drawing], weight[drawing], missed[drawing], window_m),
        misses=_misses(
            strokes, types, xy=xy, weight=weight, stroke=stroke, missed=drawing & missed
        ),
    )


def _render(doc: Drawing, *, flattening: float) -> Iterator[tuple[DataRecord, BackendProperties]]:
    config = Configuration(
        text_policy=TextPolicy.IGNORE,
        hatch_policy=HatchPolicy.SHOW_OUTLINE,
        line_policy=LinePolicy.SOLID,
        image_policy=ImagePolicy.IGNORE,
        # Точка - точкой: значок $PDMODE (крест, круг размером $PDSIZE) шире допуска.
        pdmode=0,
        max_flattening_distance=flattening,
    )
    recorder = Recorder()
    Frontend(RenderContext(doc), recorder, config=config).draw_layout(doc.modelspace())
    yield from recorder.player().recordings()


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


def _sample(coords: NDArray, step: float, extra: float, index: int, into: _Samples) -> bool:
    """Точки в серединах равных кусков каждого отрезка не длиннее шага; вес - длина куска."""
    if len(coords) == 1:
        into.xy.append(coords[:1])
        into.weight.append(np.zeros(1))
    else:
        start, end = coords[:-1], coords[1:]
        lengths = np.hypot(*(end - start).T)
        keep = lengths > 0
        if not keep.any():
            into.xy.append(coords[:1])
            into.weight.append(np.zeros(1))
        else:
            start, end, lengths = start[keep], end[keep], lengths[keep]
            counts = np.maximum(np.ceil(lengths / step).astype(np.int64), 1)
            segment = np.repeat(np.arange(len(lengths)), counts)
            offsets = np.arange(counts.sum()) - np.repeat(np.cumsum(counts) - counts, counts)
            t = (offsets + 0.5) / counts[segment]
            into.xy.append(start[segment] + (end - start)[segment] * t[:, None])
            into.weight.append((lengths / counts)[segment])
    size = len(into.xy[-1])
    into.extra.append(np.full(size, extra))
    into.stroke.append(np.full(size, index, dtype=np.int64))
    return True


def _covered(scene: Scene, xy: NDArray[np.float64], reach: NDArray[np.float64]) -> NDArray:
    geometries = [f.geometry for f in scene.features if not f.geometry.is_empty]
    covered = np.zeros(len(xy), dtype=bool)
    if not geometries:
        return covered
    tree = STRtree(geometries)
    limit = float(reach.max())
    for start in range(0, len(xy), _BATCH):
        points = shapely.points(xy[start : start + _BATCH])
        (found, _), distances = tree.query_nearest(
            points, max_distance=limit, return_distance=True, all_matches=False
        )
        near = np.zeros(len(points), dtype=bool)
        near[found] = distances <= reach[start + found]
        covered[start : start + len(points)] = near
    return covered


def _windows(
    xy: NDArray[np.float64], weight: NDArray[np.float64], missed: NDArray, size: float
) -> tuple[WindowScore, ...]:
    if not len(xy):
        return ()
    cells = np.floor(xy / size).astype(np.int64)
    keys, inverse = np.unique(cells, axis=0, return_inverse=True)
    inverse = inverse.ravel()
    ink = np.bincount(inverse, weights=weight, minlength=len(keys))
    lost = np.bincount(inverse, weights=weight * missed, minlength=len(keys))
    return tuple(
        WindowScore(float(kx * size), float(ky * size), float(i), float(m))
        for (kx, ky), i, m in zip(keys, ink, lost, strict=True)
    )


def _misses(  # noqa: PLR0913 - parallel sample arrays
    strokes: list[tuple[str, str]],
    types: list[str],
    *,
    xy: NDArray[np.float64],
    weight: NDArray[np.float64],
    stroke: NDArray[np.int64],
    missed: NDArray,
) -> tuple[InkMiss, ...]:
    lost: dict[tuple[str, str, str], float] = defaultdict(float)
    where: dict[tuple[str, str, str], tuple[float, float]] = {}
    for position in np.flatnonzero(missed):
        handle, layer = strokes[stroke[position]]
        key = (handle, types[stroke[position]], layer)
        lost[key] += float(weight[position])
        where.setdefault(key, (float(xy[position, 0]), float(xy[position, 1])))
    return tuple(
        sorted(
            (
                InkMiss(h, t, layer, round(m, 3), *where[h, t, layer])
                for (h, t, layer), m in lost.items()
            ),
            key=lambda miss: -miss.missed_m,
        )
    )


def _entity_type(doc: Drawing, handle: str) -> str:
    entity = doc.entitydb.get(handle) if handle else None
    return entity.dxftype() if entity is not None else "?"


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
