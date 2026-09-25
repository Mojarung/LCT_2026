"""An ambiguous closed CAD polyline can reserve space without claiming its fill."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import numpy as np
from ezdxf.entities import Arc
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


def test_crossed_lawn_polyline_stays_unknown_inside_footprint(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    doc.layers.add("Газон")
    doc.modelspace().add_lwpolyline(
        [(0, 0), (40, 0), (40, 40), (0, 40)], close=True, dxfattribs={"layer": "Газон"}
    )
    doc.modelspace().add_lwpolyline(
        [(10, 10), (20, 20), (10, 20), (20, 10)],
        close=True,
        dxfattribs={"layer": "Газон"},
    )
    source = tmp_path / "crossed.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source)
    require_complete_geometry(scene)
    assert scene.read_diagnostics.bounded_uncertainty_by_type == {"LWPOLYLINE": 1}
    classified, _ = classify_scene(scene, YamlLayerMapSource(ROOT / "config/layer_map.yaml").load())
    uncertain = next(feature for feature in classified.features if feature.uncertain_footprint)
    assert uncertain.object_class is ObjectClass.UNCERTAIN_AREA
    surface = build_surface_map(classified.features, [], box(0, 0, 40, 40), 0.5)
    assert surface is not None
    assert surface.material(np.array([Point(15, 15)], dtype=object))[0] == Material.UNKNOWN
    assert surface.material(np.array([Point(30, 30)], dtype=object))[0] == Material.SOIL


def test_rotated_millimetre_crossed_bulge_is_enclosed(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 4
    block = doc.blocks.new("unknown")
    source_polyline = block.add_lwpolyline(
        [(0, 0, 0, 0, 0.5), (1000, 1000, 0, 0, 0), (0, 1000, 0, 0, 0), (1000, 0, 0, 0, 0)],
        format="xyseb",
        close=True,
    )
    insert = doc.modelspace().add_blockref(
        block.name, (100_000, 200_000), dxfattribs={"rotation": 37, "xscale": 2, "yscale": 2}
    )
    source = tmp_path / "nested.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source)
    require_complete_geometry(scene)
    assert len(scene.features) == 1
    feature = scene.features[0]
    assert feature.uncertain_footprint
    assert feature.block == block.name
    assert 4 < feature.geometry.area < 12
    for edge in source_polyline.virtual_entities():
        points = (
            edge.flattening(0.0001) if isinstance(edge, Arc) else (edge.dxf.start, edge.dxf.end)
        )
        for point in points:
            transformed = insert.matrix44().transform(Vec3(point))
            assert feature.geometry.buffer(1e-8).covers(
                Point(transformed.x / 1000, transformed.y / 1000)
            )
