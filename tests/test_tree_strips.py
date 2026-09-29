"""Полоса деревьев: ряд кружков условного знака - одна полоса, а не десятки стволов.

Знак «Полоса деревьев» - кружки через 0,7-0,8 м (Кустанайская, 24.09.2026). Стволы так часто
не растут, это рисунок полосы; по стволу на кружок перепись насчитала бы фантомные деревья.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
from shapely.geometry import MultiPoint, Point, box
from test_pipeline_synthetic import ROOT

from green.application.classification import classify_scene
from green.application.params import PlanParams
from green.application.stock import stock_of
from green.application.surfaces import _seeds
from green.application.tree_strips import chain_tree_strips
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from pathlib import Path

    from green.domain.objects import Scene

STRIP_LAYER = "Полоса деревьев"


def _circles(tmp_path: Path, step: float, count: int) -> Scene:
    doc = ezdxf.new("R2018")
    doc.layers.add(STRIP_LAYER)
    for i in range(count):
        doc.modelspace().add_circle((i * step, 0), radius=0.2, dxfattribs={"layer": STRIP_LAYER})
    path = tmp_path / "strip.dxf"
    doc.saveas(path)
    layer_map = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    scene, _ = classify_scene(EzdxfSceneReader().read(path, unit="m"), layer_map, PlanParams())
    return scene


def test_twenty_circles_every_80_cm_are_one_strip(tmp_path: Path) -> None:
    scene = _circles(tmp_path, 0.8, 20)

    trees = [f for f in scene.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert len(trees) == 1
    assert trees[0].geometry.geom_type == "MultiPoint"
    assert len(trees[0].geometry.geoms) == 20
    assert trees[0].classification.method == "tree_strip"
    members = [f for f in scene.features if f.object_class is ObjectClass.IGNORE]
    assert len(members) == 20
    assert {f.classification.method for f in members} == {f"tree_strip_member:{trees[0].ref}"}


def test_isolated_marks_on_strip_layer_are_still_ambiguous(tmp_path: Path) -> None:
    scene = _circles(tmp_path, 5.0, 5)

    trees = [f for f in scene.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert [t.geometry.geom_type for t in trees] == ["MultiPoint"] * 5
    assert all(t.source_entity_type == "TREE_STRIP" for t in trees)


def test_tree_symbols_one_metre_apart_are_real_trees(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("DEREVO_1")
    block.add_circle((0, 0), radius=0.3)
    doc.layers.add(STRIP_LAYER)
    for i in range(4):
        doc.modelspace().add_blockref("DEREVO_1", (i * 1.0, 0), dxfattribs={"layer": STRIP_LAYER})
    path = tmp_path / "trees.dxf"
    doc.saveas(path)
    layer_map = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()

    scene, _ = classify_scene(EzdxfSceneReader().read(path, unit="m"), layer_map, PlanParams())

    trees = [f for f in scene.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert [(t.geometry.geom_type, t.source_entity_type) for t in trees] == [
        ("Point", "SYMBOL")
    ] * 4


def test_strip_seeds_soil_at_every_circle_not_at_its_centre() -> None:
    """Центр Г-образной полосы лежит вне неё (на тротуаре) - затравкой грунта его брать нельзя."""
    corner = [(0.0, 0.0), (0.8, 0.0), (1.6, 0.0), (1.6, 0.8), (1.6, 1.6)]
    strip = Feature(
        ref=SourceRef("00000000", "00000000", "30+strip"),
        layer=STRIP_LAYER,
        geometry=MultiPoint(corner),
        object_class=ObjectClass.EXISTING_TREE,
    )

    xy, kinds = _seeds([strip], [])

    assert sorted(map(tuple, xy.tolist())) == sorted(corner)
    assert len(kinds) == len(corner)


def test_filled_dot_on_strip_layer_keeps_footprint_without_inventing_a_tree() -> None:

    dot = Feature(
        SourceRef("file", "xref", "dot"),
        STRIP_LAYER,
        Point(5, 5).buffer(0.04),
        object_class=ObjectClass.EXISTING_TREE,
        source_entity_type="REGION",
    )
    result = chain_tree_strips([dot])
    assert result[0].geometry.equals(dot.geometry)
    assert result[0].source_entity_type == "TREE_STRIP"
    stock = stock_of(result, box(0, 0, 10, 10), crown_m=8)
    assert stock.trees == 0
    assert stock.canopy is None
