"""MLINE styles are kept as uncertain occupied areas until their meaning is reviewed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import numpy as np
from ezdxf.math import Vec3
from shapely.geometry import Point, box
from test_pipeline_synthetic import ROOT

from green.application.classification import classify_scene
from green.application.input_quality import require_complete_geometry
from green.application.surfaces import Material, build_surface_map
from green.domain.objects import ObjectClass
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from pathlib import Path


def test_mline_on_lawn_cannot_create_soil_between_parallel_strokes(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    doc.layers.add("Газон")
    doc.modelspace().add_lwpolyline(
        [(0, 0), (40, 0), (40, 40), (0, 40)], close=True, dxfattribs={"layer": "Газон"}
    )
    doc.modelspace().add_mline(
        [(10, 10), (30, 10)], dxfattribs={"layer": "Газон", "scale_factor": 2}
    )
    source = tmp_path / "multiline.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source)
    require_complete_geometry(scene)
    assert scene.read_diagnostics.bounded_uncertainty_by_type == {"MLINE": 1}
    classified, _ = classify_scene(scene, YamlLayerMapSource(ROOT / "config/layer_map.yaml").load())
    mline = next(
        feature for feature in classified.features if feature.source_entity_type == "MLINE"
    )
    assert mline.uncertain_footprint
    assert mline.object_class is ObjectClass.UNCERTAIN_AREA
    surface = build_surface_map(classified.features, [], box(0, 0, 40, 40), 0.5)
    assert surface is not None
    assert surface.material(np.array([Point(20, 10)], dtype=object))[0] == Material.UNKNOWN
    assert surface.material(np.array([Point(20, 20)], dtype=object))[0] == Material.SOIL


def test_nested_rotated_mline_keeps_all_visible_strokes(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 4
    block = doc.blocks.new("unfamiliar")
    original = block.add_mline([(0, 0), (1000, 0), (1000, 2000)])
    insert = doc.modelspace().add_blockref(
        block.name, (100_000, 200_000), dxfattribs={"rotation": 37, "xscale": 2, "yscale": 2}
    )
    source = tmp_path / "nested.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source)
    require_complete_geometry(scene)
    assert len(scene.features) == 1
    feature = scene.features[0]
    assert feature.source_entity_type == "MLINE"
    assert feature.uncertain_footprint
    assert feature.block == block.name
    for part in original.virtual_entities():
        assert part.dxftype() == "LINE"
        for point in (part.dxf.start, part.dxf.end):
            transformed = insert.matrix44().transform(Vec3(point))
            assert feature.geometry.buffer(1e-8).covers(
                Point(transformed.x / 1000, transformed.y / 1000)
            )
