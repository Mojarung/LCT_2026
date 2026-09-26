"""Сквозной прогон на синтетическом топоплане в конвенциях Геотреста.

Улица шириной 60 м: проезжая часть внизу («А»), борт по y=20, газон выше («ГАЗОН»),
водопровод d=300 по y=40, здание вверху. Материалы имеют замкнутые границы.
Проверяется: посадки только на грунте выше борта,
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
from shapely.geometry import LineString, MultiLineString, Point, box

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


def _street(
    path: Path, *, scale: float = 1.0, insunits: int = 6, material_areas: bool = True
) -> None:
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
    if material_areas:
        msp.add_lwpolyline(
            [at(0, CURB_Y), at(120, CURB_Y), at(120, 55), at(0, 55)],
            close=True,
            dxfattribs={"layer": "Леса и газоны"},
        )
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


@pytest.fixture(scope="module", params=("greedy", "milp", "portfolio"))
def run(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> dict[str, object]:
    work = tmp_path_factory.mktemp("street")
    source = work / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=work / "runs"))
    # Ряд кустарника у борта, кустарник под кронами и группы на газоне проверяются своими тестами
    # (tests/test_shrub_rows.py, tests/test_pipeline_levers.py): эти писались под план из
    # деревьев и по нему сверяют аллею, газон и блоки видов.
    params = container.profiles.load(
        "strict",
        {
            "max_rejections": 50,
            "placement_solver": request.param,
            "shrub_rows": False,
            "understory": False,
            "shrub_fill": False,
        },
    )
    report = container.use_case.execute(PlanRequest("test", source, work / "out", "strict", params))
    artifacts = container.artifacts.save(work / "out", report)
    return {"report": report, "artifacts": artifacts, "source": source, "solver": request.param}


def test_finite_selection_evidence_is_separate_from_final_plan(run: dict[str, object]) -> None:
    artifacts = run["artifacts"]
    payload = orjson.loads(artifacts["selection.json"].read_bytes())  # type: ignore[index]
    if run["solver"] == "greedy":
        assert payload is None
    elif run["solver"] == "milp":
        assert payload["objective"] >= payload["baseline_objective"]
        assert payload["upper_bound"] >= payload["objective"]
        assert payload["candidates"] >= len(payload["selected"]) > 0
        assert "before species assignment" in payload["scope"]
    else:
        portfolio = orjson.loads(artifacts["portfolio.json"].read_bytes())  # type: ignore[index]
        baseline = portfolio["variants"][0]
        chosen = next(v for v in portfolio["variants"] if v["name"] == portfolio["chosen"])
        assert len(portfolio["variants"]) >= 4
        assert chosen["valid"]
        assert chosen["quality_index"] >= baseline["quality_index"]


def test_placements_stand_on_soil_above_the_curb(run: dict[str, object]) -> None:
    plan = run["report"].plan  # type: ignore[attr-defined]
    assert len(plan.placements) >= 10
    assert sum(p.species.is_tree for p in plan.placements) >= 10
    curb = MultiLineString([[(x, CURB_Y), (x + 0.7, CURB_Y)] for x in range(120)])
    for p in plan.placements:
        assert p.y >= CURB_Y + (1.6 if p.species.is_tree else 0.5) - 1e-6
        assert curb.distance(Point(p.x, p.y)) >= (2.0 if p.species.is_tree else 1.0) - 1e-3
    assert all(p.verdict.value == "allowed" for p in plan.placements)


def test_both_modes_contribute(run: dict[str, object]) -> None:
    plan = run["report"].plan  # type: ignore[attr-defined]
    modes = {note for p in plan.placements for note in p.notes}
    assert {"аллея вдоль борта", "заполнение газона"} <= modes
    if any(p.species.is_shrub for p in plan.placements):
        assert "группа кустарников на месте дерева" in modes


def test_water_distance_is_measured_to_pipe_wall(run: dict[str, object]) -> None:
    plan = run["report"].plan  # type: ignore[attr-defined]
    for placement in plan.placements:
        if not placement.species.is_tree:
            continue  # this table has no shrub-water distance requirement
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
    assert sum(summary.counts.values()) == sum(p.species.is_tree for p in plan.placements)
    # Квоты профиля мягкие (notes/34): перебор доли вида допустим и виден в сводке, но
    # потолок хвойных жёсткий - его перебора нет.
    assert all("хвойн" not in violation for violation in summary.quota_violations)
    shrubs = plan.shrub_assortment_summary
    if any(p.species.is_shrub for p in plan.placements):
        assert shrubs is not None
        assert sum(shrubs.counts.values()) == sum(p.species.is_shrub for p in plan.placements)


def test_assortment_artifacts_are_written(run: dict[str, object]) -> None:
    artifacts = run["artifacts"]  # type: ignore[assignment]
    path = artifacts["assortment.json"]  # type: ignore[index]
    assert path.exists()
    payload = orjson.loads(path.read_bytes())
    assert payload["counts"]
    assert set(payload["decor_by_month"]) == {str(month) for month in range(1, 13)}
    assert payload["solver"] in {"milp", "greedy"}
    validation = orjson.loads(artifacts["validation.json"].read_bytes())  # type: ignore[index]
    assert validation["ok"] is True
    assert validation["checked_placements"] > 0
    assert validation["assumptions"]
    exported = orjson.loads(artifacts["export_validation.json"].read_bytes())  # type: ignore[index]
    assert exported["ok"] is True
    assert exported["expected_placements"] == exported["found_placements"]
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
    assert zones["allowed"] > 500  # useful area remains after whole-cell certification
    for zone in report.plan.zones:  # type: ignore[attr-defined]
        assert box(0, 0, 120, 60).covers(zone.geometry)
        pipe = LineString([(0, PIPE_Y), (120, PIPE_Y)])
        assert zone.geometry.distance(pipe) - PIPE_DIAMETER_M / 2 >= WATER_RULE_M - 1e-3
    doc = ezdxf.readfile(report.output_dxf)  # type: ignore[attr-defined]
    assert "GREEN_ZONE_ALLOWED" in doc.layers
    assert len(doc.modelspace().query("HATCH[layer=='GREEN_ZONE_ALLOWED']")) >= 1
    for layer, is_tree in (("GREEN_TREES", True), ("GREEN_SHRUBS", False)):
        assert len(doc.modelspace().query(f"INSERT[layer=='{layer}']")) == sum(
            p.species.is_tree == is_tree
            for p in report.plan.placements  # type: ignore[attr-defined]
        )
    assert run["artifacts"]["zones.geojson"].exists()  # type: ignore[index]


def test_lawns_cover_free_soil_and_reach_the_dxf(run: dict[str, object]) -> None:
    """П. 3 ТЗ, травянистые покрытия: газон - грунт в границе работ, который посадки оставили
    свободным, на своём слое GREEN_LAWN; исходник цел, выгрузка совпадает с планом."""
    report = run["report"]
    plan = report.plan  # type: ignore[attr-defined]
    soil = report.surface.soil_area  # type: ignore[attr-defined]
    assert plan.lawns
    assert soil is not None
    for lawn in plan.lawns:
        assert lawn.kind.value == "kept"  # весь грунт улицы - контур слоя «Леса и газоны»
        assert box(0, 0, 120, 60).covers(lawn.geometry)
        assert lawn.geometry.difference(soil).area < 1e-6
        for p in plan.placements:
            params = run["report"].params  # type: ignore[attr-defined]
            pit = params.planting_radius_m if p.species.is_tree else params.shrub_planting_radius_m
            assert lawn.geometry.distance(Point(p.x, p.y)) >= pit - 1e-6
    texts = {e.subject_id: e for e in plan.explanations}
    for lawn in plan.lawns:
        assert texts[lawn.lawn_id].kind == "lawn"
        assert "R-LAWN-KEPT-001" in texts[lawn.lawn_id].text
    summary = report.summary()  # type: ignore[attr-defined]
    assert summary["lawn_m2"] == pytest.approx(sum(g.area_m2 for g in plan.lawns), abs=0.1)
    assert summary["lawn_kept_m2"] == summary["lawn_m2"]

    doc = ezdxf.readfile(report.output_dxf)  # type: ignore[attr-defined]
    assert "GREEN_LAWN" in doc.layers
    hatches = doc.modelspace().query("HATCH[layer=='GREEN_LAWN']")
    assert len(hatches) == len(plan.lawns)
    assert {h.get_xdata("LCT_GREEN")[0].value for h in hatches} == {g.lawn_id for g in plan.lawns}
    assert {h.dxf.pattern_name for h in hatches} == {"GRASS"}
    assert report.integrity.ok  # type: ignore[attr-defined]
    exported = report.export_validation  # type: ignore[attr-defined]
    assert exported.ok
    assert exported.expected_lawns == exported.found_lawns == len(plan.lawns)

    artifacts = run["artifacts"]
    payload = orjson.loads(artifacts["plan.json"].read_bytes())  # type: ignore[index]
    assert [g["id"] for g in payload["lawns"]] == [g.lawn_id for g in plan.lawns]
    assert payload["lawns"][0]["geometry"]["type"] == "Polygon"
    assert payload["lawns"][0]["planting_type"] == "lawn"
    rows = artifacts["interpretations.csv"].read_text(encoding="utf-8-sig")  # type: ignore[index]
    assert any(line.startswith("lawn;") for line in rows.splitlines())


def test_every_assigned_species_gets_its_own_block_in_the_result(run: dict[str, object]) -> None:
    """Подобранные виды доезжают до чертежа: у каждого свой блок и свой атрибут SPECIES."""
    report = run["report"]
    plan = report.plan  # type: ignore[attr-defined]
    doc = ezdxf.readfile(report.output_dxf)  # type: ignore[attr-defined]
    codes = {p.species.code for p in plan.placements}
    assert len(codes) > 1
    blocks = {b.name for b in doc.blocks}
    for p in plan.placements:
        prefix = "GREEN_TREE" if p.species.is_tree else "GREEN_SHRUB"
        assert f"{prefix}_{p.species.code.upper()}" in blocks
    names = {
        attrib.dxf.text
        for insert in doc.modelspace().query("INSERT")
        if insert.dxf.layer in {"GREEN_TREES", "GREEN_SHRUBS"}
        for attrib in insert.attribs
        if attrib.dxf.tag == "SPECIES"
    }
    assert names == {p.species.name_ru for p in plan.placements}


def test_unfinished_material_contours_produce_no_confirmed_planting(tmp_path: Path) -> None:
    source = tmp_path / "open-materials.dxf"
    _street(source, material_areas=False)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    # Строгий режим тиммейта: грунт только в замкнутой подтверждённой грани.
    params = container.profiles.load(
        "strict", {"placement_solver": "greedy", "surface_inference_mode": "closed_faces"}
    )
    report = container.use_case.execute(
        PlanRequest("open", source, tmp_path / "out", "strict", params)
    )
    assert not report.plan.placements
    assert any("замкнут" in warning for warning in report.warnings)


def test_hybrid_default_plants_by_labels_of_unfinished_contours(tmp_path: Path) -> None:
    """Вопрос 3 пользователя: незамкнутый газон с подписью - грунт по близости подписи,
    и отчёт об этом говорит; план не пуст."""
    source = tmp_path / "open-materials.dxf"
    _street(source, material_areas=False)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"placement_solver": "greedy"})
    report = container.use_case.execute(
        PlanRequest("open", source, tmp_path / "out", "strict", params)
    )
    assert report.plan.placements
    assert any("по близости подписи" in warning for warning in report.warnings)
    assert report.summary()["surface_inference_review_required"] is False


def test_explicit_distance_mode_is_marked_for_surface_review(tmp_path: Path) -> None:
    source = tmp_path / "exploratory.dxf"
    _street(source, material_areas=False)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load(
        "strict", {"placement_solver": "greedy", "surface_inference_mode": "distance"}
    )
    report = container.use_case.execute(
        PlanRequest("sketch", source, tmp_path / "out", "strict", params)
    )
    assert report.plan.placements
    assert report.summary()["surface_inference_review_required"] is True
    assert any("Исследовательский режим покрытий" in warning for warning in report.warnings)


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
