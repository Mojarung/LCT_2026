"""Сквозной прогон на синтетическом топоплане в конвенциях Геотреста.

Улица шириной 60 м: проезжая часть внизу («А»), борт по y=20, газон выше («ГАЗОН»),
водопровод d=300 по y=40, здание вверху. Проверяется: посадки только на грунте выше борта,
отступ до водопровода мерится до наружной стенки трубы, оба приёма дали посадки,
слои зон записаны, исходные сущности не тронуты.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import pytest

from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
CURB_Y = 20.0
PIPE_Y = 40.0
PIPE_DIAMETER_M = 0.3
WATER_RULE_M = 2.0


def _street(path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    msp = doc.modelspace()
    for layer in (
        "Граница заказа",
        "Бортовой камень",
        "Граница улицы",
        "Леса и газоны",
        "Водопровод",
        "Здания",
    ):
        doc.layers.add(layer)
    msp.add_lwpolyline(
        [(0, 0), (120, 0), (120, 60), (0, 60)], close=True, dxfattribs={"layer": "Граница заказа"}
    )
    for x in range(0, 120, 1):  # штрихи борта по 0.7 м, как в топоплане
        msp.add_line((x, CURB_Y), (x + 0.7, CURB_Y), dxfattribs={"layer": "Бортовой камень"})
    msp.add_text("А", dxfattribs={"layer": "Граница улицы"}).set_placement((60, 10))
    msp.add_text("ГАЗОН", dxfattribs={"layer": "Леса и газоны"}).set_placement((60, 30))
    msp.add_line((0, PIPE_Y), (120, PIPE_Y), dxfattribs={"layer": "Водопровод"})
    msp.add_text("d=300ст.", dxfattribs={"layer": "Водопровод"}).set_placement((60, PIPE_Y + 0.5))
    msp.add_lwpolyline(
        [(0, 55), (120, 55), (120, 60), (0, 60)], close=True, dxfattribs={"layer": "Здания"}
    )
    doc.saveas(path)


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    work = tmp_path_factory.mktemp("street")
    source = work / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50})
    report = container.use_case.execute(PlanRequest("test", source, work / "out", "strict", params))
    artifacts = container.artifacts.save(work / "out", report)
    return {"report": report, "artifacts": artifacts, "source": source}


def test_placements_stand_on_soil_above_the_curb(run: dict[str, object]) -> None:
    plan = run["report"].plan  # type: ignore[attr-defined]
    assert len(plan.placements) >= 10
    assert all(p.y > CURB_Y + WATER_RULE_M - 1e-6 for p in plan.placements)
    assert all(p.verdict.value == "allowed" for p in plan.placements)


def test_both_modes_contribute(run: dict[str, object]) -> None:
    plan = run["report"].plan  # type: ignore[attr-defined]
    modes = {note for p in plan.placements for note in p.notes}
    assert modes == {"аллея вдоль борта", "заполнение газона"}


def test_water_distance_is_measured_to_pipe_wall(run: dict[str, object]) -> None:
    plan = run["report"].plan  # type: ignore[attr-defined]
    for placement in plan.placements:
        axis = abs(placement.y - PIPE_Y)
        assert axis - PIPE_DIAMETER_M / 2 >= WATER_RULE_M - 1e-3
        water = next(c for c in placement.checks if c.rule_id == "R-WATER-TREE-001")
        assert water.measured_m is not None
        assert math.isclose(water.measured_m, axis - PIPE_DIAMETER_M / 2, abs_tol=0.01)


def test_zones_and_integrity(run: dict[str, object]) -> None:
    report = run["report"]  # type: ignore[assignment]
    assert report.integrity.ok  # type: ignore[attr-defined]
    zones = {z.verdict.value: z.area_m2 for z in report.plan.zones}  # type: ignore[attr-defined]
    assert zones["allowed"] > 1000
    doc = ezdxf.readfile(report.output_dxf)  # type: ignore[attr-defined]
    assert "GREEN_ZONE_ALLOWED" in doc.layers
    assert len(doc.modelspace().query("HATCH[layer=='GREEN_ZONE_ALLOWED']")) >= 1
    assert len(doc.modelspace().query("INSERT[layer=='GREEN_TREES']")) == len(
        report.plan.placements  # type: ignore[attr-defined]
    )
    assert run["artifacts"]["zones.geojson"].exists()  # type: ignore[index]
