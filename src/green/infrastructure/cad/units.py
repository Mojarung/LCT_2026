"""Declared DXF units or an explicit project override, never a guess from site size.

Geometry alone cannot distinguish a small millimetre drawing from a large metre
drawing. Pilot files with incorrect headers need an explicit override. Unitless
input requires one too. Blocks retain their explicit INSERT scale; their unit
metadata must not cause a second, implicit conversion (ezdxf units documentation).

A header that the geometry clearly contradicts is not guessed around either: it stops
the run and names the numbers, so the override is always explicit (Peschanyy: a
millimetre template header over a metre survey, the street would shrink a thousandfold).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ezdxf import units
from ezdxf.enums import InsertUnits

from green.application.errors import InputError

if TYPE_CHECKING:
    from ezdxf.document import Drawing
    from ezdxf.entities import DXFGraphic
    from ezdxf.layouts import BaseLayout
    from numpy.typing import NDArray

AUTO = "auto"
EXPLICIT_UNITS = {
    "m": 1.0,
    "dm": 0.1,
    "cm": 0.01,
    "mm": 0.001,
    "km": 1000.0,
    "in": 0.0254,
    "ft": 0.3048,
    "yd": 0.9144,
}
_HEADER_NAMES = {
    0: "не заданы",
    1: "дюймы",
    2: "футы",
    3: "мили",
    4: "миллиметры",
    5: "сантиметры",
    6: "метры",
    7: "километры",
    14: "дециметры",
}
_METRES = 6
_UNITLESS = 0
# Разброс меряется между 2-м и 98-м процентилями: одиночная сущность в стороне (мусор после
# конвертации, подпись вне листа) не должна решать за весь чертёж.
_PERCENTILES = (2.0, 98.0)
# На нескольких десятках точек процентили ничего не значат (лист из одних вставок XREF даёт
# разброс 0): тогда точки собираются и внутри вставок.
_MIN_ANCHORS = 100
_MAX_DEPTH = 4
_MAX_POINTS = 2_000_000


@dataclass(frozen=True, slots=True)
class UnitDecision:
    """Сколько метров в единице чертежа и почему так решено."""

    unit_m: float
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Spread:
    """Где лежит основная масса чертежа: рамка между процентилями и медианная высота текста."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float
    text_height: float | None = None
    # Полная рамка всех точек привязки. Для единиц она не годится (одна сущность в стороне
    # решала бы за чертёж), а для вопроса «лежат ли два файла в одном месте» нужна она:
    # рамка между процентилями у улицы из штрихов борта вырождается в линию.
    bounds: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def size(self) -> float:
        return max(self.width, self.height)

    def describe(self) -> str:
        text = "" if self.text_height is None else f", высота текста {self.text_height:g}"
        return f"разброс координат {self.width:.0f} x {self.height:.0f} единиц{text}"


def decide_units(doc: Drawing, requested: str = AUTO) -> UnitDecision:
    code = int(doc.header.get("$INSUNITS", _UNITLESS) or _UNITLESS)
    header = f"$INSUNITS={code} ({_HEADER_NAMES.get(code, 'неизвестные единицы')})"
    if requested != AUTO:
        if requested not in EXPLICIT_UNITS:
            allowed = ", ".join([AUTO, *EXPLICIT_UNITS])
            raise InputError(
                f"drawing_unit: неизвестное значение {requested!r}, допустимо: {allowed}"
            )
        unit_m = EXPLICIT_UNITS[requested]
        note = f"Единицы чертежа заданы параметром drawing_unit={requested}, заголовок: {header}."
        return UnitDecision(unit_m, (note + _RESCALED_TAIL,))
    if code == _UNITLESS:
        raise InputError(f"Единицы чертежа не заданы ({header}); задайте drawing_unit явно")
    try:
        factor = units.conversion_factor(InsertUnits(code), InsertUnits.Meters)
    except (ValueError, TypeError, IndexError, ZeroDivisionError) as exc:
        raise InputError(f"Неизвестные единицы {header}; задайте drawing_unit явно") from exc
    if not np.isfinite(factor) or factor <= 0:
        raise InputError(f"Некорректные единицы {header}; задайте drawing_unit явно")
    conflict = _geometry_conflict(doc, factor)
    if conflict is not None:
        raise InputError(
            f"Единицы чертежа спорят с геометрией: {header}, но {conflict}. Задайте единицы "
            "явно: drawing_unit=m, если координаты в метрах, или drawing_unit=mm, если заголовок "
            "верен."
        )
    note = f"Единицы: приняты объявленные {header}; 1 единица = {factor:g} м."
    return UnitDecision(factor, () if code == _METRES else (note + _RESCALED_TAIL,))


# Заголовок верен, пока геометрия ему явно не противоречит (решение 23.09.2026: исправление
# заголовка - только явным drawing_unit). Явное противоречие - два признака сразу, как в
# docs/notes/19: участок короче 10 м по заголовку при тексте метровой высоты (в метровом
# чертеже текст 0,5-5 единиц, в миллиметровом 1:500 - от 250), или участок больше 100 км.
_MIN_SITE_M = 10.0
_MAX_SITE_M = 100_000.0
_METRE_TEXT_UNITS = 20.0


def _geometry_conflict(doc: Drawing, factor: float) -> str | None:
    """Чем геометрия противоречит объявленным единицам; None - не противоречит."""
    spread = measure(doc)
    if spread is None:
        return None
    size = max(spread.width, spread.height)
    text = spread.text_height
    extent = f"разброс координат {spread.width:.0f} x {spread.height:.0f} единиц"
    if factor < 1 and size * factor < _MIN_SITE_M and text is not None and text < _METRE_TEXT_UNITS:
        return (
            f"геометрия метровая: {extent} (по заголовку {size * factor:.2f} м, меньше "
            f"{_MIN_SITE_M:g} м), высота текста {text:g} единиц"
        )
    if factor >= 1 and size * factor > _MAX_SITE_M and (text is None or text >= _METRE_TEXT_UNITS):
        return f"геометрия не метровая: {extent} (по заголовку {size * factor / 1000:.0f} км)"
    return None


_RESCALED_TAIL = (
    " Расчёт ведётся в метрах, результат записан в единицах чертежа. В plan.json, "
    "interpretations и zones.geojson координаты в метрах."
)


def measure(doc: Drawing) -> Spread | None:
    """Разброс координат модели. Документ не меняется.

    `ezdxf.bbox.extents` здесь нельзя: он отрисовывает MULTILEADER, а отрисовка создаёт в документе
    блок стрелки. Исходный чертёж получал сущность, которой в нём не было
    (docs/notes/22-source-document-untouched.md).
    """
    collector = _Collector(doc)
    collector.layout(doc.modelspace(), None, 1.0, depth=_MAX_DEPTH)  # только сама модель
    if collector.count < _MIN_ANCHORS:
        collector.reset()
        collector.layout(doc.modelspace(), None, 1.0, depth=0)
    return collector.spread()


@dataclass(slots=True)
class _Anchors:
    """Точки привязки одного блока в его собственных координатах и вставки внутри него."""

    points: NDArray[np.float64]
    heights: NDArray[np.float64]
    inserts: list[tuple[str, NDArray[np.float64], float]]


class _Collector:
    def __init__(self, doc: Drawing) -> None:
        self._doc = doc
        self._cache: dict[str, _Anchors] = {}
        self._points: list[NDArray[np.float64]] = []
        self._heights: list[NDArray[np.float64]] = []
        self.count = 0

    def reset(self) -> None:
        """Собранные точки сбрасываются, разобранные блоки остаются."""
        self._points.clear()
        self._heights.clear()
        self.count = 0

    def layout(
        self, layout: BaseLayout, matrix: NDArray[np.float64] | None, scale: float, *, depth: int
    ) -> None:
        anchors = self._anchors(layout)
        points = anchors.points
        if matrix is not None and len(points):
            points = (
                np.column_stack([points, np.zeros(len(points)), np.ones(len(points))]) @ matrix
            )[:, :2]
        self._points.append(points)
        self._heights.append(anchors.heights * scale)
        self.count += len(points)
        if depth >= _MAX_DEPTH:
            return
        for name, local, local_scale in anchors.inserts:
            if self.count > _MAX_POINTS:
                return
            block = self._doc.blocks.get(name)
            if block is None:
                continue
            child = local if matrix is None else local @ matrix
            self.layout(block, child, scale * local_scale, depth=depth + 1)

    def _anchors(self, layout: BaseLayout) -> _Anchors:
        cached = self._cache.get(layout.layout_key)
        if cached is not None:
            return cached
        points: list[tuple[float, float]] = []
        heights: list[float] = []
        inserts: list[tuple[str, NDArray[np.float64], float]] = []
        for entity in layout:
            point = _anchor(entity)
            if point is not None:
                points.append(point)
            height = _text_height(entity)
            if height:
                heights.append(height)
            if entity.dxftype() == "INSERT":
                matrix = _insert_matrix(entity)
                if matrix is not None:
                    scale = abs(float(entity.dxf.get("xscale", 1.0))) or 1.0
                    inserts.append((entity.dxf.name, matrix, scale))
        anchors = _Anchors(
            points=np.asarray(points, dtype=np.float64).reshape(-1, 2),
            heights=np.asarray(heights, dtype=np.float64),
            inserts=inserts,
        )
        self._cache[layout.layout_key] = anchors
        return anchors

    def spread(self) -> Spread | None:
        points = np.concatenate(self._points) if self._points else np.empty((0, 2))
        if not len(points):
            return None
        heights = np.concatenate(self._heights)
        (low_x, low_y), (high_x, high_y) = np.percentile(points, _PERCENTILES, axis=0)
        return Spread(
            float(low_x),
            float(low_y),
            float(high_x),
            float(high_y),
            float(np.median(heights)) if len(heights) else None,
            bounds=(
                float(points[:, 0].min()),
                float(points[:, 1].min()),
                float(points[:, 0].max()),
                float(points[:, 1].max()),
            ),
        )


def _insert_matrix(entity: DXFGraphic) -> NDArray[np.float64] | None:
    try:
        rows = entity.matrix44().rows()  # ty: ignore[unresolved-attribute]
    except ArithmeticError, ValueError, AttributeError:
        return None
    return np.asarray([list(row) for row in rows], dtype=np.float64)


def _anchor(entity: DXFGraphic) -> tuple[float, float] | None:
    """Одна точка на сущность: для оценки разброса хватает, полный габарит считать дорого."""
    kind = entity.dxftype()
    dxf = entity.dxf
    try:
        if kind == "LINE":
            point = dxf.start
        elif kind in {"INSERT", "TEXT", "MTEXT"}:
            point = dxf.insert
        elif kind in {"CIRCLE", "ARC", "ELLIPSE"}:
            point = dxf.center
        elif kind == "POINT":
            point = dxf.location
        elif kind == "POLYLINE":
            point = entity.vertices[0].dxf.location  # ty: ignore[unresolved-attribute]
        elif kind == "LWPOLYLINE":
            first = entity.lwpoints[0]  # ty: ignore[unresolved-attribute]
            return float(first[0]), float(first[1])
        else:
            return None
    except AttributeError, IndexError:
        return None
    return float(point.x), float(point.y)


def _text_height(entity: DXFGraphic) -> float | None:
    kind = entity.dxftype()
    if kind == "TEXT":
        return float(entity.dxf.get("height", 0.0)) or None
    if kind == "MTEXT":
        return float(entity.dxf.get("char_height", 0.0)) or None
    return None
