"""Порядок загрузки DXF: строгий загрузчик, ремонт строк, снова строгий, режим восстановления.

Режим восстановления ezdxf вдвое медленнее строгого загрузчика. На генплане Берзарина он ещё и
падал после 16,9 с разбора, и только потом начинался ремонт строк (docs/notes/23-load-time.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from test_documents_repair import _drawing_with_text

from green.application.errors import InputError
from green.infrastructure.cad.documents import load_document

if TYPE_CHECKING:
    from pathlib import Path


def test_repaired_file_is_read_by_the_fast_loader(tmp_path: Path) -> None:
    path = tmp_path / "broken_newline.dxf"
    _drawing_with_text(path, b"GREEN_REPAIR\n  </Specification>")

    doc, notes = load_document(path)

    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["GREEN_REPAIR </Specification>"]
    assert any("строковых значений 1," in note for note in notes)
    assert not any("режиме восстановления" in note for note in notes)


def test_lone_carriage_return_inside_a_value_is_removed(tmp_path: Path) -> None:
    """Одиночный CR строгий загрузчик считает переводом строки (генплан Берзарина, 1 случай)."""
    path = tmp_path / "lone_cr.dxf"
    _drawing_with_text(path, b"GREEN\rREPAIR")

    doc, notes = load_document(path)

    assert [e.dxf.text for e in doc.modelspace().query("TEXT")] == ["GREENREPAIR"]
    assert len(doc.modelspace().query("LINE")) == 1
    assert any("одиночных возвратов каретки 1" in note for note in notes)


def test_clean_file_gets_no_notes(tmp_path: Path) -> None:
    path = tmp_path / "clean.dxf"
    _drawing_with_text(path, b"GREEN_CLEAN")

    _, notes = load_document(path)

    assert notes == []


def test_garbage_is_refused_with_a_reason(tmp_path: Path) -> None:
    path = tmp_path / "garbage.dxf"
    path.write_bytes(b"this is not a drawing")

    with pytest.raises(InputError, match="garbage"):
        load_document(path)
