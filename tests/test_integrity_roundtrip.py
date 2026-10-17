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


def _with_unknown_entity(path: Path) -> None:
    """DXF с сущностью, которую ezdxf не знает (ARCALIGNEDTEXT, текст по дуге из AutoCAD Express
    Tools на посадочном плане Берзарина): ezdxf держит её как набор тегов без атрибута «layer»."""
    drawing = ezdxf.new("R2018")
    msp = drawing.modelspace()
    msp.add_line((0, 0), (1, 1))
    owner = msp.block_record_handle
    drawing.saveas(path)
    text = path.read_text(encoding="utf-8")
    raw = (
        f"  0\nARCALIGNEDTEXT\n  5\nFA11\n330\n{owner}\n100\nAcDbEntity\n  8\nПодписи\n"
        "100\nAcDbArcAlignedText\n  1\nтекст по дуге\n"
    )
    head, tail = text.split("  0\nENDSEC\n  0\nSECTION\n  2\nOBJECTS", 1)
    path.write_text(head + raw + "  0\nENDSEC\n  0\nSECTION\n  2\nOBJECTS" + tail, encoding="utf-8")


def test_entity_without_a_layer_attribute_does_not_break_the_check(tmp_path: Path) -> None:
    """Аудит Берзарина 16.10.2026: проверка целостности падала с DXFAttributeError «layer»."""
    source = tmp_path / "source.dxf"
    _with_unknown_entity(source)
    checker = EzdxfIntegrityChecker()
    report = checker.check(checker.snapshot(source), source)
    assert report.ok
    assert report.changed == ()
