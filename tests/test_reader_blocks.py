"""Чтение не исключает геометрию по имени: оформление различает классификатор."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import pytest

from green.application.classification import classify_scene
from green.domain.objects import ObjectClass
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

CABLE_LAYER = "output[1]_3_ДЖКХ-24_03233up$0$Кабель электрический"
WELL_LAYER = "output[1]_3_ДЖКХ-24_03233tp$0$Колодцы"
AXIS_BLOCK = "output[1]_3_ДЖКХ-24_03233up$0$msdElementTypeMultiLine_7"
LABEL_BLOCK = "output[1]_3_ДЖКХ-24_03233up$0$DIMTXT_3"
WELL_BLOCK = "output[1]_3_ДЖКХ-24_03233tp$0$KOLOD_2"
AXIS_LENGTH_M = 20.0


def _write_drawing(path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.layers.add(CABLE_LAYER)
    doc.layers.add(WELL_LAYER)
    axis = doc.blocks.new(AXIS_BLOCK)
    axis.add_lwpolyline([(0, 0), (AXIS_LENGTH_M, 0)], dxfattribs={"layer": "0"})
    label = doc.blocks.new(LABEL_BLOCK)
    label.add_line((0, 0), (5, 3), dxfattribs={"layer": "0"})
    label.add_text("d=400ж.б.", dxfattribs={"layer": "0"}).set_placement((5, 3))
    well = doc.blocks.new(WELL_BLOCK)
    well.add_circle((0, 0), 0.5, dxfattribs={"layer": "0"})
    msp = doc.modelspace()
    msp.add_blockref(AXIS_BLOCK, (100, 100), dxfattribs={"layer": CABLE_LAYER})
    msp.add_blockref(LABEL_BLOCK, (110, 102), dxfattribs={"layer": CABLE_LAYER})
    msp.add_blockref(WELL_BLOCK, (130, 100), dxfattribs={"layer": WELL_LAYER})
    doc.saveas(path)


def test_microstation_blocks_keep_geometry_before_semantic_classification(tmp_path: Path) -> None:
    path = tmp_path / "geotrest.dxf"
    _write_drawing(path)

    scene = EzdxfSceneReader().read(path)

    lines = [f for f in scene.features if f.geometry.geom_type == "LineString"]
    assert len(lines) == 2
    assert lines[0].layer == CABLE_LAYER
    assert abs(lines[0].geometry.length - AXIS_LENGTH_M) < 1e-6

    circles = [f for f in scene.features if f.circle_radius_m is not None]
    assert [f.block for f in circles] == [WELL_BLOCK]
    assert circles[0].geometry.geom_type == "Polygon"
    assert circles[0].geometry.area == pytest.approx(0.7854, rel=0.03)

    assert [(label.layer, label.text) for label in scene.labels] == [(CABLE_LAYER, "d=400ж.б.")]
    rules = YamlLayerMapSource(Path(__file__).resolve().parents[1] / "config/layer_map.yaml").load()
    classified, _ = classify_scene(scene, rules)
    leader = next(f for f in classified.features if f.block == LABEL_BLOCK)
    assert leader.object_class is ObjectClass.IGNORE
    assert leader.classification is not None
    assert leader.classification.method == "name_rule"
