"""Closed edge/fence polylines enclose space; they do not occupy the whole interior."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest
from test_pipeline_synthetic import _street

from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("kind", ["curb", "pavement_edge"])
def test_closed_surface_edge_allows_planting_inside_declared_material(
    tmp_path: Path, kind: str
) -> None:
    source = tmp_path / "street.dxf"
    _street(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load(
        "strict",
        {"layer_classes": {"Леса и газоны": kind}, "placement_solver": "greedy"},
    )
    report = container.use_case.execute(
        PlanRequest("closed-edge", source, tmp_path / "out", "strict", params)
    )
    assert sum(p.species.is_tree for p in report.plan.placements) >= 10
    assert report.validation is not None
    assert report.validation.ok
    assert report.integrity.ok
    assert report.export_validation is not None
    assert report.export_validation.ok


def test_closed_fence_preserves_clearance_without_occupying_declared_lawn(tmp_path: Path) -> None:
    source = tmp_path / "street.dxf"
    _street(source)
    doc = ezdxf.readfile(source)
    doc.layers.new("Ограды")
    doc.modelspace().add_lwpolyline(
        [(0, 20), (120, 20), (120, 55), (0, 55)], close=True, dxfattribs={"layer": "Ограды"}
    )
    doc.saveas(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"placement_solver": "greedy"})
    report = container.use_case.execute(
        PlanRequest("closed-fence", source, tmp_path / "out", "strict", params)
    )
    assert sum(p.species.is_tree for p in report.plan.placements) >= 10
    assert report.validation is not None
    assert report.validation.ok
    assert report.integrity.ok
    assert report.export_validation is not None
    assert report.export_validation.ok


def test_filled_curb_keeps_its_occupied_interior(tmp_path: Path) -> None:
    source = tmp_path / "street.dxf"
    _street(source)
    doc = ezdxf.readfile(source)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "Бортовой камень"})
    hatch.paths.add_polyline_path([(0, 20), (120, 20), (120, 55), (0, 55)], is_closed=True)
    doc.saveas(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"placement_solver": "greedy"})
    report = container.use_case.execute(
        PlanRequest("filled-curb", source, tmp_path / "out", "strict", params)
    )
    assert not report.plan.placements
    assert any(
        check.rule_id == "R-CURB-TREE-001" and check.measured_m == 0
        for rejection in report.plan.rejections
        for check in rejection.blocking
    )
