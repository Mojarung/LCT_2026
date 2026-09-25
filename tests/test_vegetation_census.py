"""Перепись растительности: каждое дерево исходника дошло до сцены один раз.

Знаки деревьев, кустов, массивов и газона считаются дважды: независимой переписью вставок в
DXF и по якорям классифицированной сцены. Расхождение называет класс и точку.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import ezdxf
from test_pipeline_synthetic import ROOT

from green.application.classification import classify_scene
from green.application.params import PlanParams
from green.application.vegetation import CensusRecord, vegetation_census
from green.domain.objects import ObjectClass
from green.infrastructure.cad.census import insert_census
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from pathlib import Path

SYMBOLS = """
version: 1
symbols:
  DEREVO: {class: existing_tree, role: point}
  KUST1: {class: existing_shrub, role: point}
  GAZON: {class: lawn, role: marker}
  LISTVL: {class: existing_woodland, role: marker}
  KOLOD: {class: utility.access, role: point}
"""
PLACED = [
    ("DEREVO_1", (10, 10)),
    ("DEREVO_2", (20, 10)),
    ("DEREVO_3", (30, 10)),
    ("KUST1_1", (10, 30)),
    ("KUST1_2", (12, 30)),
    ("GAZON_1", (50, 50)),
    ("LISTVL_1", (80, 50)),
    ("KOLOD_1", (5, 5)),
]


def _street(tmp_path: Path):  # noqa: ANN202
    doc = ezdxf.new("R2018")
    for name, _ in PLACED:
        doc.blocks.new(name).add_circle((0, 0), radius=0.3)
    doc.layers.add("Растительность")
    for name, point in PLACED:
        doc.modelspace().add_blockref(name, point, dxfattribs={"layer": "Растительность"})
    path = tmp_path / "street.dxf"
    doc.saveas(path)
    (tmp_path / "symbols.yaml").write_text(SYMBOLS, encoding="utf-8")
    layer_map = YamlLayerMapSource(ROOT / "config/layer_map.yaml", tmp_path / "symbols.yaml").load()
    scene, _ = classify_scene(EzdxfSceneReader().read(path, unit="m"), layer_map, PlanParams())
    records = [
        CensusRecord(r.base, r.layer, r.x, r.y)
        for r in insert_census(ezdxf.readfile(path), unit_m=scene.unit_m)
    ]
    return records, scene, layer_map.symbols


def test_every_vegetation_class_matches_the_source(tmp_path: Path) -> None:
    records, scene, catalog = _street(tmp_path)

    census = vegetation_census(records, scene, catalog)

    counts = {c.object_class: (c.source, c.scene) for c in census.classes}
    assert counts == {
        ObjectClass.EXISTING_TREE: (3, 3),
        ObjectClass.EXISTING_SHRUB: (2, 2),
        ObjectClass.EXISTING_WOODLAND: (1, 1),
        ObjectClass.LAWN: (1, 1),
    }
    assert census.matches


def test_lost_tree_anchor_is_named_with_its_point(tmp_path: Path) -> None:
    records, scene, catalog = _street(tmp_path)
    lost = next(
        f for f in scene.features if f.block == "DEREVO_2" and f.source_entity_type == "SYMBOL"
    )
    scene = replace(scene, features=tuple(f for f in scene.features if f is not lost))

    census = vegetation_census(records, scene, catalog)

    trees = next(c for c in census.classes if c.object_class is ObjectClass.EXISTING_TREE)
    assert (trees.source, trees.scene) == (3, 2)
    assert trees.missing == ((20.0, 10.0),)
    assert trees.extra == ()
    assert not census.matches


def test_explicit_reclassification_is_not_a_loss(tmp_path: Path) -> None:
    """Уточнение пользователя меняет класс якоря, но знак из исходника дошёл до сцены."""
    records, scene, catalog = _street(tmp_path)
    scene = replace(
        scene,
        features=tuple(
            replace(f, object_class=ObjectClass.IGNORE) if f.block == "DEREVO_3" else f
            for f in scene.features
        ),
    )

    assert vegetation_census(records, scene, catalog).matches
