"""Saved-DXF mutations must not pass an in-memory certificate."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import ezdxf
import pytest
from shapely.geometry import box

from green.domain.norms import LawnKind, PlantingType, RuleBook
from green.domain.planting import Lawn, Placement, Plan, Species, Verdict
from green.infrastructure.cad.export_validation import check_written_plan
from green.infrastructure.cad.integrity import EzdxfIntegrityChecker
from green.infrastructure.cad.writer import EzdxfPlanWriter

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("kind", ["layer", "block"])
def test_original_green_names_are_still_protected(tmp_path: Path, kind: str) -> None:
    doc = ezdxf.new("R2018")
    doc.layers.add("GREEN_NATIVE_SURVEY")
    owner = doc.modelspace() if kind == "layer" else doc.blocks.new("GREEN_NATIVE_BLOCK")
    line = owner.add_line((0, 0), (10, 0), dxfattribs={"layer": "GREEN_NATIVE_SURVEY"})
    source = tmp_path / "source.dxf"
    doc.saveas(source)
    checker = EzdxfIntegrityChecker()
    before = checker.snapshot(source)
    line.dxf.end = (100, 0)
    result = tmp_path / "result.dxf"
    doc.saveas(result)
    assert not checker.check(before, result).ok


# Подмена атрибута вставки: вид, сквозной номер, позиция ведомости.
TAMPERED_ATTRIBUTES = {
    "species": ("SPECIES", "Wrong species"),
    "number": ("NUM", "100"),
    "position": ("POS", "2"),
}


@pytest.fixture(params=[1.0, 0.001, 0.3048])
def exported(tmp_path: Path, request: pytest.FixtureRequest):  # noqa: ANN201
    unit = request.param
    source = tmp_path / "source.dxf"
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (100, 0))
    doc.saveas(source)
    species = Species("arbitrary_species", "Тестовый вид", "Testus specius", 4)
    p = Placement(
        "plant-1", 1, PlantingType.TREE, species, 123456.789, -4321.123, Verdict.ALLOWED, ()
    )
    plan = Plan((p,), ())
    target = tmp_path / "result.dxf"
    EzdxfPlanWriter(text_font="DejaVuSans").write(
        source, plan, RuleBook({}, (), "test"), target, unit_m=unit
    )
    return target, plan, unit


def test_saved_plan_matches_for_different_drawing_units(exported) -> None:  # noqa: ANN001
    path, plan, unit = exported
    report = check_written_plan(path, plan, unit_m=unit)
    assert report.ok
    assert report.expected_placements == report.found_placements == 1


@pytest.mark.parametrize(
    "mutation",
    [
        "delete",
        "duplicate",
        "coordinate",
        "scale",
        "species",
        "number",
        "position",
        "symbol",
        "layer",
        "verdict",
        "label_text",
        "label_moved",
        "label_deleted",
        "label_duplicate",
    ],
)
def test_saved_plan_corruption_is_detected(exported, mutation: str) -> None:  # noqa: ANN001, C901, PLR0912
    path, plan, unit = exported
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    insert = msp.query("INSERT[layer=='GREEN_TREES']").first
    # Подпись позиции ведомости у посадки - обычный TEXT, его LibreCAD рисует, а атрибут - нет.
    label = msp.query("TEXT[layer=='GREEN_LABELS']").first
    if mutation.startswith("label"):
        assert label is not None, "у посадки нет подписи позиции"
    if mutation == "label_text":
        label.dxf.text = "2"
    elif mutation == "label_moved":
        label.dxf.insert = label.dxf.insert.replace(x=label.dxf.insert.x + 1.0 / unit)  # на 1 м
    elif mutation == "label_deleted":
        msp.delete_entity(label)
    elif mutation == "label_duplicate":
        msp.add_entity(label.copy())
    elif mutation == "delete":
        msp.delete_entity(insert)
    elif mutation == "duplicate":
        msp.add_entity(insert.copy())
    elif mutation == "coordinate":
        insert.dxf.insert = (0, 0)
    elif mutation == "scale":
        insert.dxf.xscale = 0.001 / unit
    elif mutation in TAMPERED_ATTRIBUTES:
        tag, value = TAMPERED_ATTRIBUTES[mutation]
        insert.get_attrib(tag).dxf.text = value
    elif mutation == "symbol":
        doc.blocks.get(insert.dxf.name).query("CIRCLE").first.dxf.radius = 0.01
    elif mutation == "layer":
        insert.dxf.layer = "0"
    elif mutation == "verdict":
        insert.set_xdata("LCT_GREEN", [(1000, "plant-1"), (1000, "needs_approval")])
    doc.saveas(path)
    report = check_written_plan(path, plan, unit_m=unit)
    assert not report.ok
    # Текст уходит в ошибку прогона в реестре: посадка первой, дальше по-русски.
    for issue in report.issues:
        assert issue.startswith("plant-1: "), issue
        assert re.search("[а-яё]", issue), issue


@pytest.mark.parametrize(
    ("mutation", "detail"),
    [
        ("delete", "lawn-1: газон не записан в DXF"),
        ("kind", "lawn-1: вид газона в XDATA не совпадает с планом"),
    ],
    ids=["delete", "kind"],
)
def test_lawn_corruption_is_reported_in_russian(tmp_path: Path, mutation: str, detail: str) -> None:
    source = tmp_path / "source.dxf"
    doc = ezdxf.new("R2018")
    doc.modelspace().add_line((0, 0), (100, 0))
    doc.saveas(source)
    lawn = Lawn("lawn-1", 1, LawnKind.KEPT, box(0, 0, 10, 5), ("R-TEST",))
    plan = Plan((), (), lawns=(lawn,))
    target = tmp_path / "result.dxf"
    EzdxfPlanWriter(text_font="DejaVuSans").write(
        source, plan, RuleBook({}, (), "test"), target, unit_m=1.0
    )
    assert check_written_plan(target, plan, unit_m=1.0).ok
    written = ezdxf.readfile(target)
    hatch = written.modelspace().query("HATCH[layer=='GREEN_LAWN']").first
    if mutation == "delete":
        written.modelspace().delete_entity(hatch)
    else:
        hatch.set_xdata("LCT_GREEN", [(1000, "lawn-1"), (1000, "new")])
    written.saveas(target)

    report = check_written_plan(target, plan, unit_m=1.0)

    assert detail in report.issues
