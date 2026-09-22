"""Declared units and explicit corrections preserve the physical plan and DXF output scale."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import pytest
from test_pipeline_synthetic import ROOT, _street

from green.application.errors import InputError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.cad.units import decide_units

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.results import RunReport

MM = 1000.0
INSUNITS_MM = 4
INSUNITS_FEET = 2


def _run(work: Path, name: str, *, drawing_unit: str = "auto", **street: float) -> RunReport:
    source = work / f"{name}.dxf"
    _street(source, **street)  # type: ignore[arg-type]
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50, "drawing_unit": drawing_unit})
    return container.use_case.execute(
        PlanRequest(name, source, work / f"out_{name}", "strict", params)
    )


@pytest.fixture(scope="module")
def reports(tmp_path_factory: pytest.TempPathFactory) -> dict[str, RunReport]:
    work = tmp_path_factory.mktemp("units")
    return {
        "metres": _run(work, "metres"),
        "millimetres": _run(work, "millimetres", scale=MM, insunits=INSUNITS_MM),
        "lying_header": _run(work, "lying_header", drawing_unit="m", insunits=INSUNITS_MM),
    }


def test_millimetre_drawing_gives_the_same_plan(reports: dict[str, RunReport]) -> None:
    metres, millimetres = reports["metres"].plan, reports["millimetres"].plan
    assert len(millimetres.placements) == len(metres.placements) >= 10
    for ours, theirs in zip(millimetres.placements, metres.placements, strict=True):
        assert math.isclose(ours.x, theirs.x, abs_tol=1e-6)
        assert math.isclose(ours.y, theirs.y, abs_tol=1e-6)
        assert ours.species.code == theirs.species.code
    assert any("приняты объявленные" in w for w in reports["millimetres"].warnings)


def test_result_is_written_in_drawing_units(reports: dict[str, RunReport]) -> None:
    report = reports["millimetres"]
    assert report.integrity.ok
    doc = ezdxf.readfile(report.output_dxf)
    inserts = doc.modelspace().query("INSERT[layer=='GREEN_TREES']")
    assert len(inserts) == sum(1 for p in report.plan.placements if p.species.is_tree)
    placed = {(round(p.x * MM), round(p.y * MM)) for p in report.plan.placements}
    for insert in inserts:
        assert (round(insert.dxf.insert.x), round(insert.dxf.insert.y)) in placed
        assert math.isclose(insert.dxf.xscale, MM)
        assert math.isclose(insert.dxf.yscale, MM)
        number = next(a for a in insert.attribs if a.dxf.tag == "NUM")
        assert math.isclose(number.dxf.height, 0.5 * MM, rel_tol=1e-6)
    zone = doc.modelspace().query("HATCH[layer=='GREEN_ZONE_ALLOWED']").first
    xs = [vertex[0] for path in zone.paths for vertex in path.vertices]
    assert max(xs) > MM  # зона допустимости тоже в миллиметрах


def test_incorrect_header_is_corrected_only_by_explicit_override(
    reports: dict[str, RunReport],
) -> None:
    lying, metres = reports["lying_header"], reports["metres"]
    assert len(lying.plan.placements) == len(metres.plan.placements)
    assert any("drawing_unit=m" in w and "$INSUNITS=4" in w for w in lying.warnings)
    assert not any("Единицы" in w for w in metres.warnings)


def test_imperial_header_is_reported_and_applied(tmp_path: Path) -> None:
    source = tmp_path / "feet.dxf"
    _street(source, insunits=INSUNITS_FEET)
    decision = decide_units(ezdxf.readfile(source))
    assert decision.unit_m == pytest.approx(0.3048)
    assert "футы" in decision.notes[0]
    assert "приняты объявленные" in decision.notes[0]


def test_unitless_input_requires_scale_instead_of_guessing_from_extent(tmp_path: Path) -> None:
    source = tmp_path / "unitless_mm.dxf"
    _street(source, scale=MM, insunits=0)
    with pytest.raises(InputError, match="drawing_unit"):
        decide_units(ezdxf.readfile(source))


def test_explicit_unit_wins_over_detection(tmp_path: Path) -> None:
    source = tmp_path / "unitless_mm.dxf"
    _street(source, scale=MM, insunits=0)
    doc = ezdxf.readfile(source)
    assert decide_units(doc, "mm").unit_m == 1 / MM
    assert decide_units(doc, "m").unit_m == 1.0
    with pytest.raises(InputError, match="drawing_unit"):
        decide_units(doc, "parsec")


def test_stray_entity_does_not_decide_for_the_drawing(tmp_path: Path) -> None:
    """Одна линия в тысяче километров от листа - мусор конвертации, а не признак миллиметров."""
    source = tmp_path / "stray.dxf"
    _street(source)
    doc = ezdxf.readfile(source)
    doc.modelspace().add_line((1e6, 1e6), (1e6 + 1, 1e6), dxfattribs={"layer": "0"})
    decision = decide_units(doc)
    assert decision.unit_m == 1.0
    assert decision.notes == ()
