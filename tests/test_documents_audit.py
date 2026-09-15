"""Строгая загрузка с аудитом: висячие handle в DXF от конвертеров не ломают сохранение."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import ezdxf

from green.infrastructure.cad.documents import load_document

if TYPE_CHECKING:
    from pathlib import Path

_BYLAYER_MATERIAL = re.compile(r"(\n\s*3\nByLayer\n\s*3[56]0\n)[0-9A-Fa-f]+")


def test_dangling_material_handle_is_audited_before_use(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    drawing = ezdxf.new("R2018")
    drawing.modelspace().add_line((0, 0), (1, 1))
    drawing.saveas(source)
    text, replaced = _BYLAYER_MATERIAL.subn(r"\g<1>FFFFF9", source.read_text("utf-8"), count=1)
    assert replaced == 1
    source.write_text(text, "utf-8")

    doc, notes = load_document(source)

    assert notes
    assert "аудит" in notes[0]
    target = tmp_path / "target.dxf"
    doc.saveas(target)
    assert ezdxf.readfile(target).materials.get("ByLayer") is not None
