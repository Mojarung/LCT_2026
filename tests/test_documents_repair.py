"""Ремонт строк DXF, которые LibreDWG режет посреди «\\U+XXXX» и сырых переводов строк.

Строгий загрузчик ezdxf одиночный «\\U+» пропускает, падает режим восстановления, когда
пары «код-значение» уже съехали из-за сырого перевода строки. Так было на генплане Берзарина.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf

from green.infrastructure.cad.documents import load_document

if TYPE_CHECKING:
    from pathlib import Path

MARKER = b"GREEN_REPAIR_MARKER"


def _drawing_with_text(path: Path, replacement: bytes) -> None:
    doc = ezdxf.new("R2018")
    doc.modelspace().add_text(MARKER.decode())
    doc.modelspace().add_line((0, 0), (5, 0))
    doc.saveas(path)
    raw = path.read_bytes()
    assert raw.count(MARKER) == 1
    path.write_bytes(raw.replace(MARKER, replacement))


def test_raw_line_break_inside_value_is_joined(tmp_path: Path) -> None:
    path = tmp_path / "broken_newline.dxf"
    _drawing_with_text(path, b"GREEN_REPAIR\n  </Specification>")

    doc, notes = load_document(path)

    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["GREEN_REPAIR </Specification>"]
    assert len(doc.modelspace().query("LINE")) == 1
    assert any("строковых значений 1," in note for note in notes)


def test_blank_tail_line_inside_file_is_joined(tmp_path: Path) -> None:
    """Строка из пробелов посреди файла это хвост значения, а не код группы (Берзарина)."""
    path = tmp_path / "broken_blank.dxf"
    _drawing_with_text(path, b"GREEN_REPAIR\n   ")

    doc, notes = load_document(path)

    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["GREEN_REPAIR"]
    assert any("строковых значений 1," in note for note in notes)


def test_split_escape_and_line_break_are_repaired_together(tmp_path: Path) -> None:
    path = tmp_path / "broken_escape.dxf"
    _drawing_with_text(path, b"d=400\\U+0\n422 tail")

    doc, notes = load_document(path)

    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["d=400?0 422 tail"]
    assert any("строковых значений 1," in note and "\\U+ 1" in note for note in notes)


def test_utf8_letter_split_across_continuation_lines_is_rejoined(tmp_path: Path) -> None:
    """LibreDWG режет длинный MTEXT на строки кода 3 посреди буквы UTF-8 (чертёж «ИС ЗИЛ
    озеленение.dwg» жюри): без ремонта текст читается суррогатами и не сериализуется."""
    path = tmp_path / "split_utf8.dxf"
    doc = ezdxf.new("R2018")
    doc.modelspace().add_mtext("MARKER")
    doc.saveas(path)
    letter = "ш".encode()  # два байта: начальный и продолжения
    raw = path.read_bytes()
    eol = b"\r\n" if b"\r\n" in raw else b"\n"
    marker = b"  1" + eol + b"MARKER"
    assert raw.count(marker) == 1
    # Первый кусок текста - код 3, последний - код 1; буква «ш» разрезана между ними.
    split = (
        b"  3"
        + eol
        + "Липа ".encode()
        + letter[:1]
        + eol
        + b"  1"
        + eol
        + letter[1:]
        + "ирокая".encode()
    )
    path.write_bytes(raw.replace(marker, split))

    loaded, notes = load_document(path)

    (mtext,) = loaded.modelspace().query("MTEXT")
    assert mtext.text == "Липа широкая"
    assert any("разрезанных переводом строки, 1" in note for note in notes)


def test_split_utf8_pattern_is_ignored_in_cp1251_drawings(tmp_path: Path) -> None:
    """В DXF до 2007 (cp1251) байты 0x80-0xBF - обычные символы, их не трогаем."""
    path = tmp_path / "cp1251.dxf"
    doc = ezdxf.new("R2000")
    doc.modelspace().add_text("ABC")
    doc.saveas(path)

    _loaded, notes = load_document(path)

    assert not any("разрезанных" in note for note in notes)


def test_mline_style_element_without_linetype_becomes_bylayer(tmp_path: Path) -> None:
    """Пустой тип линии у элемента стиля мультилинии (LibreDWG, «2026-07-21 - СПОЗУ.dwg»)
    ронял разбор MLINE: DXFInvalidLineType. После загрузки - ByLayer, MLINE разбирается."""
    path = tmp_path / "mline.dxf"
    doc = ezdxf.new("R2018")
    doc.modelspace().add_mline([(0, 0), (10, 0)])
    doc.saveas(path)
    raw = path.read_bytes()
    marker = b"\r\n  6\r\nBYLAYER\r\n" if b"\r\n" in raw else b"\n  6\nBYLAYER\n"
    style_start = raw.index(b"MLINESTYLE")
    head, tail = raw[:style_start], raw[style_start:]
    assert marker in tail
    path.write_bytes(head + tail.replace(marker, marker.replace(b"BYLAYER", b""), 1))

    loaded, notes = load_document(path)

    (mline,) = loaded.modelspace().query("MLINE")
    assert list(mline.virtual_entities())
    assert any("мультилиний без типа линии" in note for note in notes)
