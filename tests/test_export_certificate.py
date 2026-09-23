"""Saved-DXF mutations must not pass an in-memory certificate."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest

from green.domain.norms import PlantingType, RuleBook
from green.domain.planting import Placement, Plan, Species, Verdict
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
        "symbol",
        "layer",
        "verdict",
    ],
)
def test_saved_plan_corruption_is_detected(exported, mutation: str) -> None:  # noqa: ANN001
    path, plan, unit = exported
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    insert = msp.query("INSERT[layer=='GREEN_TREES']").first
    if mutation == "delete":
        msp.delete_entity(insert)
    elif mutation == "duplicate":
        msp.add_entity(insert.copy())
    elif mutation == "coordinate":
        insert.dxf.insert = (0, 0)
    elif mutation == "scale":
        insert.dxf.xscale = 0.001 / unit
    elif mutation == "species":
        insert.get_attrib("SPECIES").dxf.text = "Wrong species"
    elif mutation == "number":
        insert.get_attrib("NUM").dxf.text = "100"
    elif mutation == "symbol":
        doc.blocks.get(insert.dxf.name).query("CIRCLE").first.dxf.radius = 0.01
    elif mutation == "layer":
        insert.dxf.layer = "0"
    elif mutation == "verdict":
        insert.set_xdata("LCT_GREEN", [(1000, "plant-1"), (1000, "needs_approval")])
    doc.saveas(path)
    assert not check_written_plan(path, plan, unit_m=unit).ok
