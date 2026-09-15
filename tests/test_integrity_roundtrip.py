"""Отпечатки целостности переживают пересохранение ezdxf без правок исходника."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf

from green.infrastructure.cad.integrity import EzdxfIntegrityChecker

if TYPE_CHECKING:
    from pathlib import Path


def test_explicit_default_tags_and_empty_regions_do_not_count_as_changes(tmp_path: Path) -> None:
    source = tmp_path / "source.dxf"
    drawing = ezdxf.new("R2018")
    msp = drawing.modelspace()
    # Явно записанное значение по умолчанию: файловый писатель ezdxf такой тег опускает,
    # как это бывает в DXF от LibreDWG.
    msp.add_lwpolyline([(0, 0), (10, 0), (10, 5)], dxfattribs={"const_width": 0.0})
    msp.add_line((0, 0), (1, 1))
    # REGION без ACIS-данных ezdxf не экспортирует вовсе.
    msp.add_region()
    drawing.saveas(source)

    checker = EzdxfIntegrityChecker()
    snapshot = checker.snapshot(source)
    resaved = tmp_path / "resaved.dxf"
    ezdxf.readfile(source).saveas(resaved)

    report = checker.check(snapshot, resaved)

    assert report.ok
    assert report.changed == ()
    assert report.missing == ()
