"""Знак решает раньше слоя: экземпляр знака - один объект, его штрихи - рисунок.

Раньше на слое «Полоса деревьев» круг знака DEREVO становился вторым деревом, а линия знака -
газоном; куст KUST1 считался деревом, массив LISTVL - газоном (Кустанайская, 24.09.2026).
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import ezdxf
import pytest
from test_pipeline_synthetic import ROOT

from green.application.classification import (
    ClassificationError,
    classification_report,
    classify_scene,
    require_classified,
)
from green.application.params import PlanParams
from green.domain.objects import ObjectClass
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing

SYMBOLS = """
version: 1
symbols:
  DEREVO: {class: existing_tree, role: point}
  KUST1: {class: existing_shrub, role: point}
  GAZON: {class: lawn, role: marker}
  OGRADA: {class: fence, role: geometry}
  STRELK: {class: ignore, role: annotation}
"""


def _symbol(doc: Drawing, name: str) -> None:
    block = doc.blocks.new(name)
    block.add_ellipse((0, 0), major_axis=(1, 0), ratio=0.5)
    block.add_circle((0, 0), radius=0.3)
    block.add_line((-0.5, 0), (0.5, 0))


def _classified(tmp_path: Path, inserts: list[tuple[str, tuple[float, float], str]], **params):  # noqa: ANN003, ANN202
    doc = ezdxf.new("R2018")
    for name in {name for name, _, _ in inserts}:
        _symbol(doc, name)
    for name, point, layer in inserts:
        if layer not in doc.layers:
            doc.layers.add(layer)
        doc.modelspace().add_blockref(name, point, dxfattribs={"layer": layer})
    path = tmp_path / "street.dxf"
    doc.saveas(path)
    (tmp_path / "symbols.yaml").write_text(SYMBOLS, encoding="utf-8")
    layer_map = YamlLayerMapSource(ROOT / "config/layer_map.yaml", tmp_path / "symbols.yaml").load()
    scene = EzdxfSceneReader().read(path, unit="m")
    classified, _ = classify_scene(scene, layer_map, PlanParams(**params))
    return classified, layer_map


def test_tree_symbol_is_one_tree_at_its_insertion_point(tmp_path: Path) -> None:
    scene, _ = _classified(tmp_path, [("DEREVO_935", (10, 20), "Полоса деревьев")])

    trees = [f for f in scene.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert [(t.geometry.x, t.geometry.y, t.source_entity_type) for t in trees] == [
        (10, 20, "SYMBOL")
    ]
    strokes = [f for f in scene.features if f.source_entity_type != "SYMBOL"]
    assert len(strokes) == 3
    assert {f.object_class for f in strokes} == {ObjectClass.IGNORE}


def test_shrub_is_a_shrub_and_lawn_marker_is_not_an_object(tmp_path: Path) -> None:
    scene, _ = _classified(
        tmp_path,
        [("KUST1_162", (5, 5), "Полоса деревьев"), ("GAZON_3", (30, 30), "Леса и газоны")],
    )

    points = Counter(
        (f.object_class, f.source_entity_type)
        for f in scene.features
        if f.source_entity_type in {"SYMBOL", "SYMBOL_MARKER"}
    )
    assert points == {
        (ObjectClass.EXISTING_SHRUB, "SYMBOL"): 1,
        (ObjectClass.LAWN, "SYMBOL_MARKER"): 1,
    }
    assert ObjectClass.EXISTING_TREE not in {f.object_class for f in scene.features}


def test_geometry_symbol_keeps_its_strokes_as_the_object(tmp_path: Path) -> None:
    scene, _ = _classified(tmp_path, [("OGRADA_1", (0, 0), "0")])

    assert {f.object_class for f in scene.features} == {ObjectClass.FENCE}
    assert len(scene.features) == 3


def test_unknown_symbol_stops_a_verified_run_instead_of_a_layer_guess(tmp_path: Path) -> None:
    scene, layer_map = _classified(
        tmp_path, [("NEZNAKOMY_7", (1, 1), "Полоса деревьев")], infer_unknown=False
    )

    assert {f.object_class for f in scene.features} == {ObjectClass.UNKNOWN}
    verified = PlanParams(infer_unknown=False)
    report = classification_report(scene, layer_map, verified)
    with pytest.raises(ClassificationError):
        require_classified(report, verified, scene=scene)


def test_unknown_symbol_on_a_tree_layer_is_inferred_a_tree(tmp_path: Path) -> None:
    """Задача 14: незнакомый код на слое со словом «деревьев» - дерево в точке вставки."""
    scene, _ = _classified(tmp_path, [("NEZNAKOMY_7", (1, 1), "Полоса деревьев")])

    trees = [f for f in scene.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert [(t.geometry.x, t.geometry.y) for t in trees] == [(1, 1)]
    assert trees[0].classification.method == "symbol_inferred:NEZNAKOMY:дерев"
    assert ObjectClass.UNKNOWN not in {f.object_class for f in scene.features}


def test_unknown_symbol_without_words_is_a_point_obstacle(tmp_path: Path) -> None:
    """Слов нет ни в блоке, ни в слое - небольшой знак на земле: препятствие в точке."""
    scene, _ = _classified(tmp_path, [("QX_7", (4, 5), "Level 3")])

    points = [f for f in scene.features if f.source_entity_type == "SYMBOL"]
    assert [(p.object_class, p.geometry.x, p.geometry.y) for p in points] == [
        (ObjectClass.OBSTACLE, 4, 5)
    ]
    assert points[0].classification.method == "symbol_assumed:QX"


def test_explicit_block_class_beats_the_dictionary(tmp_path: Path) -> None:
    scene, _ = _classified(
        tmp_path,
        [("DEREVO_935", (10, 20), "Полоса деревьев")],
        block_classes={"DEREVO_935": "ignore"},
    )

    assert ObjectClass.EXISTING_TREE not in {f.object_class for f in scene.features}


def test_without_a_dictionary_strokes_follow_the_layer_map(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    _symbol(doc, "DEREVO_935")
    doc.layers.add("Полоса деревьев")
    doc.modelspace().add_blockref("DEREVO_935", (10, 20), dxfattribs={"layer": "Полоса деревьев"})
    path = tmp_path / "street.dxf"
    doc.saveas(path)
    missing = tmp_path / "no-symbols.yaml"
    layer_map = YamlLayerMapSource(ROOT / "config/layer_map.yaml", missing).load()

    scene, _ = classify_scene(EzdxfSceneReader().read(path, unit="m"), layer_map, PlanParams())

    assert not layer_map.symbols
    assert "SYMBOL" not in {f.source_entity_type for f in scene.features}


def test_well_symbol_keeps_its_drawn_outline_for_clearances(tmp_path: Path) -> None:
    """Отступ от колодца меряется от наружной стенки: точка в центре занизила бы его."""
    doc = ezdxf.new("R2018")
    well = doc.blocks.new("KOLOD_17")
    well.add_circle((0, 0), radius=0.5)
    doc.layers.add("Колодцы")
    doc.modelspace().add_blockref("KOLOD_17", (40, 40), dxfattribs={"layer": "Колодцы"})
    path = tmp_path / "well.dxf"
    doc.saveas(path)
    (tmp_path / "symbols.yaml").write_text(
        "version: 1\nsymbols:\n  KOLOD: {class: utility.access, role: point}\n", encoding="utf-8"
    )
    layer_map = YamlLayerMapSource(ROOT / "config/layer_map.yaml", tmp_path / "symbols.yaml").load()

    scene, _ = classify_scene(EzdxfSceneReader().read(path, unit="m"), layer_map, PlanParams())

    wells = [f for f in scene.features if f.source_entity_type == "SYMBOL"]
    assert len(wells) == 1
    assert wells[0].object_class is ObjectClass.UTILITY_ACCESS
    assert wells[0].geometry.bounds == pytest.approx((39.5, 39.5, 40.5, 40.5), abs=0.1)
