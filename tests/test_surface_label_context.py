"""Material words in annotations/legends must not silently become area evidence."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import ezdxf
import numpy as np
import pytest
from shapely.geometry import Point, box

from green.application.classification import (
    classification_report,
    classify_scene,
    require_classified,
)
from green.application.errors import InputError
from green.application.params import PlanParams
from green.application.surfaces import Material, build_surface_map
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]
RULES = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()


def source(path: Path, layer: str, block: str | None = None) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    for name in {"Бортовой камень", layer} - {"0"}:
        doc.layers.new(name)
    doc.modelspace().add_lwpolyline(
        [(0, 0), (20, 0), (20, 20), (0, 20)], close=True, dxfattribs={"layer": "Бортовой камень"}
    )
    if block:
        symbol = doc.blocks.new(block)
        symbol.add_text("ГАЗОН", dxfattribs={"insert": (0, 0), "layer": "0"})
        doc.modelspace().add_blockref(block, (10, 10), dxfattribs={"layer": layer})
    else:
        doc.modelspace().add_text("ГАЗОН", dxfattribs={"insert": (10, 10), "layer": layer})
    doc.saveas(path)


@pytest.mark.parametrize(
    ("layer", "block"),
    [
        ("Пояснительные", None),
        ("Условные_штампы", None),
        ("0", "DIMTXT_legend"),
        ("Газон демонтаж", None),
    ],
)
def test_annotation_and_work_labels_do_not_supply_soil(
    tmp_path: Path, layer: str, block: str | None
) -> None:
    path = tmp_path / "source.dxf"
    source(path, layer, block)
    scene, _ = classify_scene(EzdxfSceneReader().read(path), RULES)
    surface = build_surface_map(scene.features, scene.labels, box(0, 0, 20, 20), 0.5)
    assert (
        surface is None
        or surface.material(np.array([Point(10, 10)], dtype=object))[0] != Material.SOIL
    )


def test_ordinary_label_still_identifies_closed_face(tmp_path: Path) -> None:
    path = tmp_path / "source.dxf"
    source(path, "Материал покрытия")
    scene, _ = classify_scene(EzdxfSceneReader().read(path), RULES)
    surface = build_surface_map(scene.features, scene.labels, box(0, 0, 20, 20), 0.5)
    assert surface.material(np.array([Point(10, 10)], dtype=object))[0] == Material.SOIL


def test_nested_legend_and_attached_attribute_keep_context(tmp_path: Path) -> None:
    path = tmp_path / "nested.dxf"
    source(path, "0")
    doc = ezdxf.readfile(path)
    for entity in list(doc.modelspace().query("TEXT")):
        doc.modelspace().delete_entity(entity)
    inner = doc.blocks.new("Inner")
    inner.add_text("ГАЗОН", dxfattribs={"insert": (0, 0)})
    outer = doc.blocks.new("DIMTXT_legend")
    outer.add_blockref("Inner", (0, 0))
    instance = doc.modelspace().add_blockref("DIMTXT_legend", (10, 10))
    instance.add_attrib("NOTE", "ГАЗОН", (12, 10))
    doc.saveas(path)
    scene, _ = classify_scene(EzdxfSceneReader().read(path), RULES)
    assert len(scene.labels) == 2
    assert all(label.surface_role == "ignore" for label in scene.labels)
    nested = next(label for label in scene.labels if label.block == "Inner")
    assert nested.block_chain == ("DIMTXT_legend", "Inner")
    assert (nested.x, nested.y) == (10, 10)
    report = classification_report(scene, RULES)
    assert report.labels == report.excluded_surface_labels == 2
    assert sum(g.labels for g in report.label_groups) == 2


@pytest.mark.parametrize(
    ("role", "expected"), [("soil", Material.SOIL), ("paved", Material.PAVED), ("ignore", None)]
)
def test_explicit_label_role_supports_unfamiliar_legend(
    tmp_path: Path, role: str, expected: Material | None
) -> None:
    path = tmp_path / "explicit.dxf"
    source(path, "Пояснительные")
    scene = EzdxfSceneReader().read(path)
    scene = replace(scene, labels=(replace(scene.labels[0], text="M-17"),))
    ref = str(scene.labels[0].ref)
    params = PlanParams(label_roles={ref.lower(): role}, semantic_source_sha256=scene.source_sha256)
    scene, _ = classify_scene(scene, RULES, params)
    require_classified(classification_report(scene, RULES, params), params)
    label = scene.labels[0]
    assert label.surface_role == role
    assert label.surface_evidence.method == "explicit_label"
    assert label.text == "M-17"  # retained for other consumers, not deleted
    surface = build_surface_map(scene.features, scene.labels, box(0, 0, 20, 20), 0.5)
    if expected is None:
        assert surface is None
    else:
        assert surface.material(np.array([Point(10, 10)], dtype=object))[0] == expected


@pytest.mark.parametrize(
    "overrides", [{"": "soil"}, {"ABC": "soil", "abc": "paved"}, {"x": "typo"}]
)
def test_invalid_label_roles_rejected(tmp_path: Path, overrides: dict[str, str]) -> None:
    path = tmp_path / "bad.dxf"
    source(path, "0")
    with pytest.raises(InputError, match="label_roles"):
        classify_scene(EzdxfSceneReader().read(path), RULES, PlanParams(label_roles=overrides))


def test_unused_label_assignment_does_not_silently_pass(tmp_path: Path) -> None:
    path = tmp_path / "bad.dxf"
    source(path, "0")
    params = PlanParams(label_roles={"nonexistent": "soil"}, require_known_objects=False)
    scene, _ = classify_scene(EzdxfSceneReader().read(path), RULES, params)
    report = classification_report(scene, RULES, params)
    assert report.unused_overrides == ("label_roles:nonexistent",)
    with pytest.raises(InputError):
        require_classified(report, params)
