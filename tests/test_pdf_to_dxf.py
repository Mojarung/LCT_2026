"""Векторный PDF чертежа -> DXF по слоям и совмещение листов (tools/pdf_to_dxf.py).

У Фрунзенской набережной в материалах пилота есть только PDF-экспорты листов из AutoCAD:
слои чертежа сохранены как группы необязательного содержимого (OCG), а улица разрезана на
пять листов с линиями совмещения «Лист N». Проверяется разбор потока, имена слоёв, масштаб и
совмещение листов по подписям и вершинам.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import ezdxf
import numpy as np
import pytest
import shapely
import shapely.ops
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    TextStringObject,
)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import pdf_to_dxf as tool  # noqa: E402

POINT_AT_500_M = 0.0254 / 72 * 500


def test_tokens_read_numbers_names_strings_and_skip_inline_images() -> None:
    data = b"1 -2.5 .5 /OC (a\\(b\\)c \\101) <0041 00> BI /W 1 ID \x00\xff EI q"

    assert list(tool.tokens(data)) == [
        ("number", 1.0),
        ("number", -2.5),
        ("number", 0.5),
        ("name", "OC"),
        ("string", b"a(b)c A"),
        ("string", b"\x00\x41\x00"),
        ("op", "BI"),
        ("name", "W"),
        ("number", 1.0),
        ("op", "q"),
    ]


def test_matrices_compose_like_pdf_and_rigid_moves_invert() -> None:
    scale = (2.0, 0.0, 0.0, 2.0, 0.0, 0.0)
    shift = (1.0, 0.0, 0.0, 1.0, 10.0, 0.0)
    # cm умножает слева: сначала масштаб, потом сдвиг.
    assert tool.apply(tool.multiply(scale, shift), 1, 1) == (12.0, 2.0)
    m = tool.rigid(math.radians(30), 5.0, -3.0)
    back = tool.move(tool.invert(m), tool.move(m, np.array([[7.0, 11.0]])))
    assert np.allclose(back, [[7.0, 11.0]])


def _pdf(path: Path) -> None:
    """Лист с двумя слоями OCG: «xref_Подоснова|ТОПО_Ограды» и «Граница работ»; линия 100 pt
    в видовом экране и подпись в таблице вне его."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=300)
    groups = []
    for name in ("xref_Подоснова|ТОПО_Ограды", "Граница работ"):
        group = DictionaryObject(
            {NameObject("/Type"): NameObject("/OCG"), NameObject("/Name"): TextStringObject(name)}
        )
        groups.append(writer._add_object(group))  # noqa: SLF001 - сборка тестового PDF
    writer._root_object[NameObject("/OCProperties")] = DictionaryObject(  # noqa: SLF001
        {
            NameObject("/OCGs"): ArrayObject(groups),
            NameObject("/D"): DictionaryObject({NameObject("/ON"): ArrayObject(groups)}),
        }
    )
    content = (
        b"q 10 10 200 200 re W n "
        b"/OC /oc1 BDC 20 20 m 120 20 l S EMC "
        b"/OC /oc2 BDC 20 40 m 60 40 l 60 80 l h S EMC "
        b"/OC /oc1 BDC 30 30 m 40 30 l S EMC "
        b"Q q 250 10 100 100 re W n /OC /oc1 BDC 260 20 m 270 20 l S EMC Q"
    )
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = writer._add_object(stream)  # noqa: SLF001
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Properties"): DictionaryObject(
                {NameObject("/oc1"): groups[0], NameObject("/oc2"): groups[1]}
            )
        }
    )
    with path.open("wb") as handle:
        writer.write(handle)


def test_page_becomes_layers_in_metres_and_only_the_viewport_is_kept(tmp_path: Path) -> None:
    source = tmp_path / "sheet.pdf"
    _pdf(source)
    reader = tool.PdfReader(source)
    plate = tool.plate(tool.read_page(reader, 0), scale=500)
    target = tmp_path / "sheet.dxf"

    counts = tool.write_plates([plate], [tool.IDENTITY], target)

    doc = ezdxf.readfile(target)
    lines = list(doc.modelspace().query("LWPOLYLINE"))
    # Видовой экран - отсечение с двумя линиями из трёх; линия таблицы вне его отброшена.
    assert counts["lines"] == len(lines) == 3
    by_layer = {e.dxf.layer for e in lines}
    assert by_layer == {"ТОПО_Ограды", "Граница работ"}
    fence = max(
        (e for e in lines if e.dxf.layer == "ТОПО_Ограды"),
        key=lambda e: abs(e.get_points()[1][0] - e.get_points()[0][0]),
    )
    length = abs(fence.get_points()[1][0] - fence.get_points()[0][0])
    assert length == pytest.approx(100 * POINT_AT_500_M)
    boundary = next(e for e in lines if e.dxf.layer == "Граница работ")
    assert boundary.closed


def _street(seed: int) -> list[tuple[str, np.ndarray, bool]]:
    rng = np.random.default_rng(seed)
    lines = []
    for _ in range(400):
        start = rng.uniform([0, 0], [300, 60])
        steps = rng.normal(0, 3, size=(4, 2)).cumsum(0)
        lines.append(("ТОПО_Ограды", start + np.vstack([[0, 0], steps]), False))
    return lines


def _plate(
    lines: list[tuple[str, np.ndarray, bool]],
    window: tuple[float, float, float, float],
    move: tool.Matrix,
    labels: list[tuple[str, float, float, float]],
) -> tool.Plate:
    box = shapely.box(*window)
    kept = [
        (name, tool.move(move, pts), shut)
        for name, pts, shut in lines
        if shapely.contains_xy(box, *pts.mean(0))
    ]
    texts = [
        ("ДВ_ГП_Линия совмещения", text, *tool.move(move, np.array([[x, y]]))[0], 2.5, angle)
        for text, x, y, angle in labels
    ]
    frame = shapely.Polygon(tool.move(move, np.asarray(box.exterior.coords)))
    return tool.Plate(kept, texts, frame)


def test_neighbour_sheets_are_aligned_by_match_line_labels_and_vertices() -> None:
    """Листы - куски одной улицы в своих координатах листа: второй повёрнут на 10° и сдвинут.
    На линии совмещения x = 150 у обоих подписи «Лист 1» и «Лист 2»; поворот подписи на
    втором листе - поворот листа."""
    street = _street(7)
    move = tool.rigid(math.radians(-10), -140.0, 30.0)
    labels = [("Лист 1", 148.0, 30.0, 90.0), ("Лист 2", 151.0, 30.0, 90.0)]
    first = _plate(street, (0, 0, 160, 60), tool.IDENTITY, labels)
    second = _plate(
        street,
        (140, 0, 300, 60),
        move,
        [(t, x, y, angle - 10.0) for t, x, y, angle in labels],
    )

    world, shares = tool.stitch([first, second])

    assert shares[0] > tool.STITCH_SHARE
    point = tool.move(move, np.array([[200.0, 20.0]]))
    assert np.allclose(tool.move(world[1], point), [[200.0, 20.0]], atol=1e-3)


def test_sheets_without_common_labels_are_refused_not_guessed() -> None:
    first = _plate(_street(1), (0, 0, 160, 60), tool.IDENTITY, [])
    second = _plate(_street(2), (140, 0, 300, 60), tool.IDENTITY, [])

    with pytest.raises(ValueError, match="не совмещаются"):
        tool.stitch([first, second])


def test_overlap_of_neighbour_sheets_is_written_once(tmp_path: Path) -> None:
    street = _street(7)
    labels = [("Лист 1", 148.0, 30.0, 90.0), ("Лист 2", 151.0, 30.0, 90.0)]
    first = _plate(street, (0, 0, 160, 60), tool.IDENTITY, labels)
    second = _plate(street, (140, 0, 300, 60), tool.IDENTITY, labels)
    target = tmp_path / "street.dxf"

    counts = tool.write_plates([first, second], [tool.IDENTITY, tool.IDENTITY], target)

    whole = sum(
        1 for _, pts, _ in street if shapely.contains_xy(shapely.box(0, 0, 300, 60), *pts.mean(0))
    )
    assert counts["lines"] == whole
    assert counts["overlap"] > 0


def _dashed_square(side: float, dash: float, gap: float) -> list[np.ndarray]:
    """Квадрат штриховой линией: штрихи dash через разрыв gap, как в PDF из AutoCAD."""
    ring = shapely.LineString([(0, 0), (side, 0), (side, side), (0, side), (0, 0)])
    pieces = []
    position = 0.0
    while position < ring.length:
        end = min(position + dash, ring.length)
        piece = shapely.ops.substring(ring, position, end)
        pieces.append(np.asarray(piece.coords))
        position = end + gap
    return pieces


def test_dashed_boundary_is_healed_into_one_closed_line() -> None:
    """Граница работ Фрунзенской из PDF - 1 225 штрихов по 3,2 м через 1,6 м: без сшивки
    граница не замыкается, и у участка нет границы работ."""
    dashes = [("ДВ_ГП_Граница работ", p, False) for p in _dashed_square(60, 3.2, 1.6)]
    fence = [
        ("ТОПО_Ограды", np.array([[0.0, 100.0], [40.0, 100.0]]), False),
        ("ТОПО_Ограды", np.array([[42.0, 100.0], [90.0, 100.0]]), False),
    ]

    lines, healed = tool.heal_dashes([*dashes, *fence])

    boundary = [line for line in lines if line[0] == "ДВ_ГП_Граница работ"]
    assert len(boundary) == 1
    assert boundary[0][2]  # замкнута
    assert shapely.Polygon(boundary[0][1]).area == pytest.approx(3600, rel=0.02)
    assert healed == {"ДВ_ГП_Граница работ": len(dashes)}
    # Ограда из двух длинных линий с калиткой 2 м - не штриховой слой: калитка остаётся.
    assert [line for line in lines if line[0] == "ТОПО_Ограды"] == fence
