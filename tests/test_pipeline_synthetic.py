"""Сквозной прогон на синтетическом топоплане в конвенциях Геотреста.

Улица шириной 60 м: проезжая часть внизу («А»), борт по y=20, газон выше («ГАЗОН»),
водопровод d=300 по y=40, здание вверху. Проверяется: посадки только на грунте выше борта,
отступ до водопровода мерится до наружной стенки трубы, оба приёма дали посадки,
слои зон записаны, исходные сущности не тронуты.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING

import ezdxf
import orjson
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


def _street(path: Path, *, scale: float = 1.0, insunits: int = 6) -> None:
    """Улица в метрах; scale=1000 и insunits=4 дают тот же чертёж в миллиметрах."""

    def at(x: float, y: float) -> tuple[float, float]:
        return (x * scale, y * scale)

    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = insunits
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
        [at(0, 0), at(120, 0), at(120, 60), at(0, 60)],
        close=True,
        dxfattribs={"layer": "Граница заказа"},
    )
    for x in range(0, 120, 1):  # штрихи борта по 0.7 м, как в топоплане
        msp.add_line(at(x, CURB_Y), at(x + 0.7, CURB_Y), dxfattribs={"layer": "Бортовой камень"})
    height = 2.5 * scale
    msp.add_text("А", height=height, dxfattribs={"layer": "Граница улицы"}).set_placement(
        at(60, 10)
    )
    msp.add_text("ГАЗОН", height=height, dxfattribs={"layer": "Леса и газоны"}).set_placement(
        at(60, 30)
    )
    msp.add_line(at(0, PIPE_Y), at(120, PIPE_Y), dxfattribs={"layer": "Водопровод"})
    msp.add_text("d=300ст.", height=height, dxfattribs={"layer": "Водопровод"}).set_placement(
        at(60, PIPE_Y + 0.5)
    )
    msp.add_lwpolyline(
        [at(0, 55), at(120, 55), at(120, 60), at(0, 60)],
        close=True,
        dxfattribs={"layer": "Здания"},
    )
    doc.saveas(path)


@pytest.fixture(scope="module")
def run(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    work = tmp_path_factory.mktemp("street")
    source = work / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    # Ряд кустарника у борта, кустарник под кронами и группы на газоне проверяются своими тестами
    # (tests/test_shrub_rows.py, tests/test_pipeline_levers.py): эти писались под план из
    # деревьев и по нему сверяют аллею, газон и блоки видов.
    params = container.profiles.load(
        "strict",
        {"max_rejections": 50, "shrub_rows": False, "understory": False, "shrub_fill": False},
    )
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
    # Кроме приёма, в заметках бывает сдвиг от нормы (application/refine): он не приём.
    labels = {"аллея вдоль борта", "заполнение газона", "группа кустарников на месте дерева"}
    modes = {note for p in plan.placements for note in p.notes if note in labels}
    assert modes == {"аллея вдоль борта", "заполнение газона"}


def test_water_distance_is_measured_to_pipe_wall(run: dict[str, object]) -> None:
    plan = run["report"].plan  # type: ignore[attr-defined]
    for placement in plan.placements:
        axis = abs(placement.y - PIPE_Y)
        assert axis - PIPE_DIAMETER_M / 2 >= WATER_RULE_M - 1e-3
        water = next(c for c in placement.checks if c.rule_id == "R-WATER-TREE-001")
        assert water.measured_m is not None
        assert math.isclose(water.measured_m, axis - PIPE_DIAMETER_M / 2, abs_tol=0.01)


def test_species_are_assigned_and_explained(run: dict[str, object]) -> None:
    plan = run["report"].plan  # type: ignore[attr-defined]
    texts = {e.subject_id: e.text for e in plan.explanations}
    for placement in plan.placements:
        assert placement.assortment is not None
        assert "Вид" in texts[placement.placement_id]
    assigned = {p.species.code for p in plan.placements if p.assortment.status == "assigned"}
    assert len(assigned) > 1, "план не должен быть монокультурой при квоте 10%"
    summary = plan.assortment_summary
    assert summary is not None
    assert summary.shannon > 0
    assert sum(summary.counts.values()) == len(plan.placements)
    assert not summary.quota_violations


def test_assortment_artifacts_are_written(run: dict[str, object]) -> None:
    artifacts = run["artifacts"]  # type: ignore[assignment]
    path = artifacts["assortment.json"]  # type: ignore[index]
    assert path.exists()
    payload = orjson.loads(path.read_bytes())
    assert payload["counts"]
    assert set(payload["decor_by_month"]) == {str(month) for month in range(1, 13)}
    assert payload["solver"] in {"milp", "greedy"}
    plan_json = orjson.loads(artifacts["plan.json"].read_bytes())  # type: ignore[index]
    first = plan_json["placements"][0]
    assert first["assortment"]["percent"] > 0
    assert first["assortment"]["factors"]
    rows = artifacts["interpretations.csv"].read_text(encoding="utf-8-sig")  # type: ignore[index]
    assert "species" in rows
    schedule = artifacts["planting_schedule.csv"].read_text(encoding="utf-8-sig")  # type: ignore[index]
    assert "Площадь под посадочные ямы" in schedule
    assert "Всего деревьев" in schedule
    assert not re.search(r";\d+\.\d{2}(;|$)", schedule, re.MULTILINE), "площади с запятой"


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


def test_every_assigned_species_gets_its_own_block_in_the_result(run: dict[str, object]) -> None:
    """Подобранные виды доезжают до чертежа: у каждого свой блок и свой атрибут SPECIES."""
    report = run["report"]
    plan = report.plan  # type: ignore[attr-defined]
    doc = ezdxf.readfile(report.output_dxf)  # type: ignore[attr-defined]
    codes = {p.species.code for p in plan.placements}
    assert len(codes) > 1
    blocks = {name for name in (b.name for b in doc.blocks) if name.startswith("GREEN_TREE_")}
    assert {f"GREEN_TREE_{code.upper()}" for code in codes} <= blocks
    names = {
        attrib.dxf.text
        for insert in doc.modelspace().query("INSERT[layer=='GREEN_TREES']")
        for attrib in insert.attribs
        if attrib.dxf.tag == "SPECIES"
    }
    assert names == {p.species.name_ru for p in plan.placements}


def test_moved_weak_places_keep_every_norm(run: dict[str, object]) -> None:
    """Сдвиг слабого места (application/refine) не имеет права купить запас нарушением."""
    plan = run["report"].plan  # type: ignore[attr-defined]
    moved = [p for p in plan.placements if any(n.startswith("сдвинута сервисом") for n in p.notes)]
    for placement in moved:
        assert placement.verdict.value != "forbidden"
        assert all(c.outcome.value != "fail" for c in placement.checks)
    assert plan.quality is not None
    assert plan.quality.index is not None
    if moved:
        assert any(w.startswith("Сдвиг от сетей:") for w in plan.warnings)
