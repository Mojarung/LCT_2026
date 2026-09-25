"""Строгая загрузка с аудитом: висячие handle в DXF от конвертеров не ломают сохранение."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.audit import AuditError, Auditor, ErrorEntry

from green.application.errors import InputError
from green.infrastructure.cad.documents import _require_safe_audit, load_document

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


def test_only_verified_empty_annotation_table_removal_is_safe(tmp_path: Path) -> None:
    auditor = Auditor(ezdxf.new("R2018"))
    auditor.fixes.append(
        ErrorEntry(
            AuditError.REMOVED_INVALID_GRAPHIC_ENTITY,
            "Removed invalid DXF entity ACAD_TABLE(#ABC) from BLOCK '*Model_Space'.",
        )
    )
    _require_safe_audit(tmp_path / "sample.dxf", auditor, empty_tables={"ABC"})
    with pytest.raises(InputError, match="потерю/изменение геометрии"):
        _require_safe_audit(tmp_path / "sample.dxf", auditor)
    auditor.fixes[0].message = "Removed invalid DXF entity HATCH(#ABC)"
    with pytest.raises(InputError, match="потерю/изменение геометрии"):
        _require_safe_audit(tmp_path / "sample.dxf", auditor, empty_tables={"ABC"})
