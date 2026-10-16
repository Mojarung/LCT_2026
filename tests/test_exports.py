"""Выгрузки для проектировщика: книга Excel и DXF только со слоями результата.

Green Leaders отдают ведомость и таблицу проверок в .xlsx (числа - числами), konstantikkov -
DXF только со слоями результата в координатах исходника, чтобы подключить его внешней ссылкой
к своему генплану (лёгкий файл даже для Олимпийской деревни).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import openpyxl
from test_writer_layout import BOOK, _mixed_plan, _write

from green.infrastructure.reports.artifacts import write_result_layers, write_workbook

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_workbook_has_the_schedule_and_every_check_with_numbers(tmp_path: Path) -> None:
    plan = _mixed_plan()
    path = write_workbook(tmp_path / "plan.xlsx", plan, BOOK)
    book = openpyxl.load_workbook(path)
    assert book.sheetnames == ["Ведомость", "Проверки"]
    schedule = list(book["Ведомость"].iter_rows(values_only=True))
    counts = [row[3] for row in schedule[1:] if isinstance(row[3], int)]
    assert sum(counts) >= len(plan.placements)
    checks = list(book["Проверки"].iter_rows(values_only=True))
    head = checks[0]
    assert "measured_m" in head
    measured = [row[head.index("measured_m")] for row in checks[1:]]
    assert measured
    assert all(isinstance(value, (int, float)) for value in measured if value is not None)


def test_result_layers_file_keeps_only_green_layers_in_source_coordinates(tmp_path: Path) -> None:
    plan = _mixed_plan()
    result = _write(tmp_path, plan)
    light = write_result_layers(result, tmp_path / "result_layers.dxf")
    doc = ezdxf.readfile(light)
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert layers
    assert all(layer.startswith("GREEN_") for layer in layers)
    source = ezdxf.readfile(result)
    inserts = sorted(
        (round(e.dxf.insert.x, 3), round(e.dxf.insert.y, 3))
        for e in source.modelspace().query("INSERT")
        if e.dxf.layer.startswith("GREEN_")
    )
    copied = sorted(
        (round(e.dxf.insert.x, 3), round(e.dxf.insert.y, 3))
        for e in doc.modelspace().query("INSERT")
    )
    assert copied == inserts


def test_layers_file_saved_under_the_pending_name_is_reused_not_reread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сценарий пишет результат во временный «.result.pending.dxf» и потом переименовывает;
    писатель кладёт рядом «.result.pending_layers.dxf». Профиль Камчатской 17.10.2026: файл не
    находился, и результат на сотни мегабайт читался заново (18 с из 210)."""
    plan = _mixed_plan()
    source = tmp_path / "source.dxf"
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (100, 0))
    doc.saveas(source)
    from green.infrastructure.cad.writer import EzdxfPlanWriter  # noqa: PLC0415

    pending = tmp_path / ".result.pending.dxf"
    EzdxfPlanWriter(text_font="DejaVuSans").write(source, plan, BOOK, pending, unit_m=1.0)
    result = tmp_path / "result.dxf"
    pending.replace(result)

    def no_reread(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("result.dxf read again")

    monkeypatch.setattr(ezdxf, "readfile", no_reread)
    light = write_result_layers(result, tmp_path / "result_layers.dxf")
    assert light.exists()
    assert not (tmp_path / ".result.pending_layers.dxf").exists()  # служебный файл не остаётся
