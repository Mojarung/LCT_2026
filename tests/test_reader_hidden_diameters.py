"""Hidden text cannot change materials or relax a known pipe-wall clearance."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import ezdxf
import pytest
import shapely
from shapely.geometry import box

from green.application.audit import AuditRequest
from green.application.classification import classify_scene
from green.application.constraints import ConstraintIndex
from green.application.diameters import assign_diameters
from green.application.params import PlanParams
from green.application.surfaces import Material, build_surface_map
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource, YamlRuleBookSource

ROOT = Path(__file__).resolve().parents[1]
MAPPING = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
BOOK = (
    YamlRuleBookSource(ROOT / "config/acts.yaml", ROOT / "config/rules.yaml")
    .load()
    .for_sp42_edition("2016")
)
WATER_RULE = tuple(r for r in BOOK.distance_rules if r.rule_id == "R-WATER-TREE-001")


def drawing(path: Path, kind: str, scale: float = 1.0, text: str = "d=400ст.") -> Path:
    doc = ezdxf.new("R2018")
    doc.units = 6 if scale == 1 else 4
    for name in ["Водопровод", "Леса и газоны"]:
        doc.layers.new(name)
    m = doc.modelspace()
    m.add_line((0, 0), (20 * scale, 0), dxfattribs={"layer": "Водопровод"})
    m.add_text(
        "ГАЗОН",
        dxfattribs={
            "layer": "Леса и газоны",
            "insert": (10 * scale, 10 * scale),
            "height": 0.2 * scale,
        },
    )
    attrs = {"layer": "Водопровод", "insert": (10 * scale, 0.2 * scale), "height": 0.2 * scale}
    if kind in {"visible", "text", "mtext"}:
        attrs["invisible"] = int(kind != "visible")
        if kind == "mtext":
            attrs["char_height"] = attrs.pop("height")
            m.add_mtext(text, dxfattribs=attrs)
        else:
            m.add_text(text, dxfattribs=attrs)
    elif kind == "attrib":
        b = doc.blocks.new("DIMTXT_META")
        ins = m.add_blockref(b.name, (0, 0), dxfattribs={"layer": "Водопровод"})
        attrs.pop("insert")
        ins.add_attrib("DIAM", text, (10 * scale, 0.2 * scale), dxfattribs={**attrs, "flags": 1})
    elif kind == "parent":
        b = doc.blocks.new("DIMTXT_LEAF")
        b.add_text(text, dxfattribs={**attrs, "layer": "0"})
        p = doc.blocks.new("DIMTXT_PARENT")
        p.add_blockref(b.name, (0, 0))
        m.add_blockref(p.name, (0, 0), dxfattribs={"layer": "Водопровод", "invisible": 1})
    doc.saveas(path)
    return path


@pytest.mark.parametrize("kind", ["visible", "text", "mtext", "attrib", "parent"])
@pytest.mark.parametrize("scale", [1.0, 1000.0])
def test_hidden_diameter_is_constraint_only_and_preserves_outer_wall_verdict(
    kind: str, scale: float, tmp_path: Path
) -> None:
    source = drawing(tmp_path / "source.dxf", kind, scale)
    before = sha256(source.read_bytes()).hexdigest()
    scene = EzdxfSceneReader().read(source)
    assert sha256(source.read_bytes()).hexdigest() == before
    assert sum(scene.read_diagnostics.visited_by_type.values()) == sum(
        scene.read_diagnostics.outcomes.values()
    )
    assert not scene.read_diagnostics.geometry_gaps
    assert scene.unit_m == 1 / scale
    assert len(scene.hidden_diameter_labels) == int(kind != "visible")
    if kind != "visible":
        hidden = scene.hidden_diameter_labels[0]
        assert (hidden.x, hidden.y) == pytest.approx((10, 0.2))
        assert hidden.surface_role == "ignore"
        assert [label.text for label in scene.labels] == ["ГАЗОН"]
        assert any("Скрытые подписи диаметров: 1" in w for w in scene.warnings)
    classified, _ = classify_scene(scene, MAPPING, PlanParams(name_model=False))
    assert classified.hidden_diameter_labels == scene.hidden_diameter_labels
    features = assign_diameters(
        classified.features, (*classified.labels, *classified.hidden_diameter_labels), 3.0
    )
    assert features[0].diameter_m == 0.4
    assert features[0].geometry.length == pytest.approx(20)
    index = ConstraintIndex(
        features, WATER_RULE, require_utility_data=False, planting_radius_m=1.24
    )
    batch = index.evaluate(shapely.points([(10, 2.1)]))
    assert batch.verdict(0).value == "forbidden"
    check = batch.checks(0)[0]
    assert check.measured_m == pytest.approx(1.9)
    assert check.threshold_m == 2.0


@pytest.mark.parametrize("text", ["А", "ГАЗОН", "КЖ9", "детская площадка"])
def test_hidden_non_diameter_text_stays_out_of_both_channels(text: str, tmp_path: Path) -> None:
    source = drawing(tmp_path / "source.dxf", "text", text=text)
    scene = EzdxfSceneReader().read(source)
    assert [label.text for label in scene.labels] == ["ГАЗОН"]
    assert not scene.hidden_diameter_labels


def test_even_mixed_diameter_material_text_never_reaches_material_inference(tmp_path: Path) -> None:
    source = drawing(tmp_path / "source.dxf", "text", text="d=400ст. асфальт")
    scene = EzdxfSceneReader().read(source)
    scene, _ = classify_scene(scene, MAPPING, PlanParams(name_model=False))
    assert scene.hidden_diameter_labels
    surface = build_surface_map(
        scene.features,
        scene.labels,
        box(0, 0, 20, 20),
        0.5,
        inference_mode="hybrid",
        open_ground=True,
    )
    assert surface.material(shapely.points([(10, 10)]))[0] == Material.SOIL
    assert all(label.text != "d=400ст. асфальт" for label in scene.labels)


def test_full_use_case_retains_hidden_diameter_but_not_hidden_material(tmp_path: Path) -> None:
    source = drawing(tmp_path / "source.dxf", "text")
    doc = ezdxf.readfile(source)
    for name in ["Граница заказа", "Бортовой камень"]:
        doc.layers.new(name)
    m = doc.modelspace()
    m.add_lwpolyline(
        [(0, -5), (30, -5), (30, 20), (0, 20)], close=True, dxfattribs={"layer": "Граница заказа"}
    )
    m.add_lwpolyline(
        [(0, -5), (30, -5), (30, 20), (0, 20)], close=True, dxfattribs={"layer": "Леса и газоны"}
    )
    m.add_line((0, -3), (30, -3), dxfattribs={"layer": "Бортовой камень"})
    m.add_text(
        "А",
        dxfattribs={"layer": "Леса и газоны", "insert": (15, 10), "height": 0.2, "invisible": 1},
    )
    doc.saveas(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load(
        "strict",
        {
            "placement_solver": "greedy",
            "refine_budget_s": 0,
            "shrub_rows": False,
            "understory": False,
            "shrub_fill": False,
            "lawns": False,
            "flowerbeds": False,
            "zones": False,
            "name_model": False,
            "assortment_mode": "single",
        },
    )
    report = container.use_case.execute(
        PlanRequest("hidden-diameter", source, tmp_path / "out", "strict", params)
    )
    assert report.integrity.ok
    assert any("Скрытые подписи диаметров: 1" in w for w in report.warnings)
    water = next(f for f in report.context.features if f.object_class.value == "utility.water")
    assert water.diameter_m == 0.4
    assert all(label.text not in {"d=400ст.", "А"} for label in report.context.labels)
    assert report.surface.material(shapely.points([(15, 10)]))[0] == Material.SOIL


def test_audit_use_case_also_retains_hidden_pipe_wall_distance(tmp_path: Path) -> None:
    source = drawing(tmp_path / "source.dxf", "text")
    doc = ezdxf.readfile(source)
    m = doc.modelspace()
    layer = "06_ДП_ЛИПА_Мелк_план"
    doc.layers.new(layer)
    m.add_circle((10, 2.1), 2.5, dxfattribs={"layer": layer})
    doc.saveas(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load("strict", {"name_model": False})
    report = container.audit.execute(
        AuditRequest(
            "hidden-audit",
            source,
            tmp_path / "out",
            "strict",
            params,
            planting_layers=r"^06_ДП_.+_план$",
        )
    )
    assert report.integrity.ok
    assert len(report.plantings) == 1
    assert any("Скрытые подписи диаметров: 1" in w for w in report.warnings)
    water_check = next(c for c in report.plantings[0].checks if c.rule_id == "R-WATER-TREE-001")
    assert water_check.measured_m == pytest.approx(1.9)
    assert water_check.outcome.value == "fail"
