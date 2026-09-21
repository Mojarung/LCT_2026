"""Демонстрационный участок: синтетический топоплан в конвенциях Мосгеотреста.

Нужен для кнопки «показать на демонстрационном участке»: на стенде жюри датасета нет, он в
репозиторий не идёт, поэтому образец обязан существовать в самом сервисе. Чертёж строится
кодом, а не лежит файлом, - тогда он не может разойтись с классификатором слоёв.

Участок сделан так, чтобы на карте было видно, ради чего сервис: широкий газон между бортом
и тротуаром, пять разных типов подземных сетей с подписанными диаметрами, здание и
существующие деревья. Это не настоящая улица и выдавать его за настоящую нельзя.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.layouts import Modelspace

SAMPLE_NAME = "Демонстрационный участок.dxf"

WIDTH_M = 200.0
DEPTH_M = 80.0
CURB_Y = 20.0
SIDEWALK_Y = 62.0
BUILDING_Y = 70.0
TEXT_HEIGHT_M = 2.0

# Сети в газоне. Разнесены так, чтобы между охранными полосами оставался коридор под посадку:
# иначе демонстрация показывала бы пустой газон и сплошные отказы.
UTILITIES: tuple[tuple[str, float, str], ...] = (
    ("Газопровод", 26.0, "d=100ст."),
    ("Водопровод", 34.0, "d=300ст."),
    ("Канализация", 42.0, "d=400кер."),
    ("Теплосеть", 50.0, "d=500ст."),
    ("Кабель связи", 57.0, ""),
)

LAYERS = (
    "Граница работ",
    "Бортовой камень",
    "Граница улицы",
    "Леса и газоны",
    "Здания",
    "ЭС_КЛ 0.4",
    "Дендра_сохранить",
    *(name for name, _, _ in UTILITIES),
)


def write_sample(path: Path) -> Path:
    """Записать демонстрационный чертёж в метрах и вернуть путь."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6  # метры
    msp = doc.modelspace()
    for layer in LAYERS:
        doc.layers.add(layer)

    msp.add_lwpolyline(
        [(0, 0), (WIDTH_M, 0), (WIDTH_M, DEPTH_M), (0, DEPTH_M)],
        close=True,
        dxfattribs={"layer": "Граница работ"},
    )

    # Борт идёт штрихами по 0,7 м, как в выгрузке топоплана, а не одной линией.
    step = 1.0
    x = 0.0
    while x < WIDTH_M:
        msp.add_line(
            (x, CURB_Y), (min(x + 0.7, WIDTH_M), CURB_Y), dxfattribs={"layer": "Бортовой камень"}
        )
        x += step

    msp.add_line((0, SIDEWALK_Y), (WIDTH_M, SIDEWALK_Y), dxfattribs={"layer": "Бортовой камень"})

    # Материал покрытия сервис читает из подписей: «А» - асфальт проезжей части, «ГАЗОН» - грунт.
    _text(msp, "А", (WIDTH_M / 2, CURB_Y / 2), "Граница улицы")
    for position in (0.25, 0.5, 0.75):
        _text(msp, "ГАЗОН", (WIDTH_M * position, 30.0), "Леса и газоны")
        _text(msp, "ГАЗОН", (WIDTH_M * position, 54.0), "Леса и газоны")

    for layer, y, label in UTILITIES:
        msp.add_line((0, y), (WIDTH_M, y), dxfattribs={"layer": layer})
        if label:
            _text(msp, label, (WIDTH_M * 0.35, y + 0.6), layer)

    # Силовой кабель идёт не через весь участок: так на карте видно, что отступы считаются
    # от фактической геометрии, а не от всей полосы.
    msp.add_line((0, 46.0), (WIDTH_M * 0.55, 46.0), dxfattribs={"layer": "ЭС_КЛ 0.4"})

    msp.add_lwpolyline(
        [(0, BUILDING_Y), (WIDTH_M, BUILDING_Y), (WIDTH_M, DEPTH_M), (0, DEPTH_M)],
        close=True,
        dxfattribs={"layer": "Здания"},
    )

    for index in range(6):
        msp.add_circle((30.0 + index * 30.0, 59.0), 2.5, dxfattribs={"layer": "Дендра_сохранить"})

    doc.saveas(path)
    return path


def _text(msp: Modelspace, value: str, at: tuple[float, float], layer: str) -> None:
    msp.add_text(value, height=TEXT_HEIGHT_M, dxfattribs={"layer": layer}).set_placement(at)
