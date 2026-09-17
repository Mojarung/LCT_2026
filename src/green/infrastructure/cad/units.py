"""Единицы чертежа: заголовку `$INSUNITS` верить нельзя, решает геометрия.

В датасете 22 DWG из 749 объявляют миллиметры, дюймы или футы. Пять из них проверены по
координатам (docs/notes/19-drawing-units.md): все в метрах в московской местной системе, заголовок
остался от шаблона. Пересчёт по заголовку превратил бы лист 255 x 255 м в 25 см. Поэтому сервис
считает чертёж метровым, пока геометрия не скажет обратное, а о расхождении пишет в предупреждения.

Настоящий чертёж в миллиметрах, сантиметрах или дециметрах пересчитывается в метры при чтении,
результат пишется обратно в единицах чертежа.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from ezdxf import bbox

from green.application.errors import InputError

if TYPE_CHECKING:
    from ezdxf.document import Drawing
    from ezdxf.entities import DXFGraphic

AUTO = "auto"
EXPLICIT_UNITS = {"m": 1.0, "dm": 0.1, "cm": 0.01, "mm": 0.001}
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
# Единицы мельче метра, которые встречаются в российских чертежах: их сервис пересчитывает.
_SMALL_METRIC = {4: 0.001, 5: 0.01, 14: 0.1}
# Участок улицы не бывает меньше 10 м: если при пересчёте по заголовку он выходит меньше,
# заголовок врёт.
_MIN_SITE_M = 10.0
# 100 км в метрах больше Москвы: такой разброс координат значит, что единица мельче метра.
_MAX_SITE_UNITS = 100_000.0
# Высота текста в метровом чертеже 0,5-5 единиц, в миллиметровом масштаба 1:500 от 250.
_TEXT_HEIGHT_NOT_METRES = 20.0
# Разброс меряется между 2-м и 98-м процентилями: одиночная сущность в стороне (мусор после
# конвертации, подпись вне листа) не должна решать за весь чертёж.
_PERCENTILES = (2.0, 98.0)
# На нескольких десятках точек процентили ничего не значат (лист из одних вставок XREF даёт
# разброс 0): тогда берётся полный габарит модели.
_MIN_ANCHORS = 100


@dataclass(frozen=True, slots=True)
class UnitDecision:
    """Сколько метров в единице чертежа и почему так решено."""

    unit_m: float
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _Geometry:
    width: float
    height: float
    text_height: float | None

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
        return UnitDecision(unit_m, (note + _RESCALED_TAIL,) if unit_m != 1.0 else ())
    geometry = _measure(doc)
    if geometry is None:
        return UnitDecision(1.0)
    factor = _SMALL_METRIC.get(code)
    if factor is not None:
        return _small_metric(factor, header, geometry)
    if geometry.size > _MAX_SITE_UNITS:
        note = (
            f"Единицы: заголовок {header}, но {geometry.describe()} - для метров это больше "
            "100 км. Координаты приняты в метрах; если чертёж в миллиметрах, задайте "
            "drawing_unit=mm."
        )
        return UnitDecision(1.0, (note,))
    if code not in {_METRES, _UNITLESS}:
        note = (
            f"Единицы: заголовок {header} не учитывается, геометрия метровая "
            f"({geometry.describe()}). Координаты приняты в метрах."
        )
        return UnitDecision(1.0, (note,))
    return UnitDecision(1.0)


_RESCALED_TAIL = (
    " Расчёт ведётся в метрах, результат записан в единицах чертежа. В plan.json, "
    "interpretations и zones.geojson координаты в метрах."
)


def _small_metric(factor: float, header: str, geometry: _Geometry) -> UnitDecision:
    text_says_metres = (
        geometry.text_height is not None and geometry.text_height < _TEXT_HEIGHT_NOT_METRES
    )
    fits_header = geometry.size * factor >= _MIN_SITE_M
    if fits_header and (geometry.size > _MAX_SITE_UNITS or not text_says_metres):
        note = f"Единицы: чертёж не в метрах: {header}, {geometry.describe()}." + _RESCALED_TAIL
        return UnitDecision(factor, (note,))
    note = (
        f"Единицы: заголовок {header}, но геометрия метровая ({geometry.describe()}). "
        "Координаты приняты в метрах; при ошибке задайте drawing_unit."
    )
    return UnitDecision(1.0, (note,))


def _measure(doc: Drawing) -> _Geometry | None:
    xs: list[float] = []
    ys: list[float] = []
    heights: list[float] = []
    for entity in doc.modelspace():
        point = _anchor(entity)
        if point is not None:
            xs.append(point[0])
            ys.append(point[1])
        height = _text_height(entity)
        if height:
            heights.append(height)
    text_height = statistics.median(heights) if heights else None
    if len(xs) < _MIN_ANCHORS:
        box = bbox.extents(doc.modelspace(), fast=True)
        if not box.has_data:
            return None
        return _Geometry(float(box.size.x), float(box.size.y), text_height)
    low_x, high_x = np.percentile(np.asarray(xs), _PERCENTILES)
    low_y, high_y = np.percentile(np.asarray(ys), _PERCENTILES)
    return _Geometry(float(high_x - low_x), float(high_y - low_y), text_height)


def _anchor(entity: DXFGraphic) -> tuple[float, float] | None:
    """Одна точка на сущность: для оценки разброса хватает, полный габарит считать дорого."""
    kind = entity.dxftype()
    dxf = entity.dxf
    try:
        if kind == "LINE":
            point = dxf.start
        elif kind in {"INSERT", "TEXT", "MTEXT"}:
            point = dxf.insert
        elif kind in {"CIRCLE", "ARC"}:
            point = dxf.center
        elif kind == "POINT":
            point = dxf.location
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
