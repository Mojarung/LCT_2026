"""Open HATCH keeps its CAD fill while uncertain material is spatially contained."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import numpy as np
import pytest
from ezdxf.math import Vec3
from ezdxf.xclip import XClip
from shapely.geometry import Point, box

from green.application.classification import classify_scene
from green.application.input_quality import require_complete_geometry
from green.application.params import PlanParams
from green.application.surfaces import Material, build_surface_map
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(("unit_code", "scale"), [(6, 1), (4, 1000)])
def test_open_hatch_reserves_only_its_footprint_without_changing_rendered_fill(
    tmp_path: Path, unit_code: int, scale: int
) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = unit_code
    model = doc.modelspace()

    def point(x: float, y: float) -> tuple[float, float]:
        return x * scale, y * scale

    def polygon(layer: str, coordinates: list[tuple[float, float]]) -> None:
        if layer not in doc.layers:
            doc.layers.new(layer)
        model.add_lwpolyline(
            [point(*xy) for xy in coordinates], close=True, dxfattribs={"layer": layer}
        )

    polygon("Граница работ", [(0, 0), (100, 0), (100, 50), (0, 50)])
    polygon("Газон", [(0, 10), (100, 10), (100, 45), (0, 45)])
    polygon("Проезжая часть", [(0, 0), (100, 0), (100, 10), (0, 10)])
    polygon("Здания", [(0, 45), (100, 45), (100, 50), (0, 50)])
    doc.layers.new("Бортовой камень")
    model.add_line(point(0, 10), point(100, 10), dxfattribs={"layer": "Бортовой камень"})
    hatch = model.add_hatch(dxfattribs={"layer": "Газон"})
    path = hatch.paths.add_edge_path()
    path.add_line(point(45, 19), point(55, 19))
    path.add_line(point(55, 31), point(45, 31))
    source = tmp_path / "open-hatch.dxf"
    doc.saveas(source)

    scene = EzdxfSceneReader().read(source)
    require_complete_geometry(scene)
    assert scene.read_diagnostics.bounded_uncertainty_by_type == {"HATCH": 1}
    feature = next(f for f in scene.features if f.source_entity_type == "HATCH")
    assert feature.geometry.area == pytest.approx(120)
    assert feature.uncertainty_footprint is not None
    assert feature.uncertainty_footprint.covers(box(45, 19, 55, 31))
    assert feature.uncertainty_footprint.area < 130

    params = PlanParams(infer_unknown=False, surface_inference_mode="closed_faces")
    classified, _ = classify_scene(
        scene, YamlLayerMapSource(ROOT / "config/layer_map.yaml").load(), params
    )
    surface = build_surface_map(classified.features, classified.labels, box(0, 0, 100, 50), 0.5)
    assert surface is not None
    points = np.array([Point(50, 25), Point(30, 25)], dtype=object)
    assert surface.material(points).tolist() == [Material.UNKNOWN, Material.SOIL]
    assert surface.fits_soil(points, 1).tolist() == [False, True]


@pytest.mark.parametrize("clip", [False, True])
def test_nested_millimetre_hatch_transforms_and_clips_uncertainty(
    tmp_path: Path, *, clip: bool
) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 4
    block = doc.blocks.new("msdElementType_hatch")
    hatch = block.add_hatch(dxfattribs={"layer": "Газон"})
    path = hatch.paths.add_edge_path()
    path.add_line((0, 0), (10000, 0))
    path.add_line((10000, 10000), (0, 10000))
    insert = doc.modelspace().add_blockref(
        block.name,
        (1000000, 500000),
        dxfattribs={"rotation": 37, "xscale": 2, "yscale": 3},
    )
    if clip:
        XClip(insert).set_block_clipping_path([(0, 0), (5000, 10000)])
    source = tmp_path / "nested.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source)
    require_complete_geometry(scene)
    feature = next(f for f in scene.features if f.source_entity_type == "HATCH")
    assert feature.geometry.area == pytest.approx(300 if clip else 600)
    footprint = feature.uncertainty_footprint
    assert footprint is not None
    assert footprint.area < 1300
    transform = insert.matrix44()
    inside = transform.transform(Vec3(2500, 5000, 0))
    outside = transform.transform(Vec3(7500, 5000, 0))
    assert footprint.covers(Point(inside.x / 1000, inside.y / 1000))
    assert footprint.covers(Point(outside.x / 1000, outside.y / 1000)) is not clip
