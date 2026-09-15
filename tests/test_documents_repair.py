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
