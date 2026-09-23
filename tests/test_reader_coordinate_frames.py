"""Coordinates come from DXF frames; size or familiar layer names cannot redefine geometry."""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
import pytest
from shapely.geometry import Polygon

from green.application.classification import classify_scene
from green.domain.objects import ObjectClass
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from green.domain.objects import Scene


def test_lwpolyline_extrusion_is_transformed_to_world_xy(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.modelspace().add_lwpolyline(
        [(2, 3), (8, 3), (8, 9), (2, 9)],
        close=True,
        dxfattribs={"extrusion": (0, 0, -1), "elevation": 7},
    )
    source = tmp_path / "negative-normal.dxf"
    doc.saveas(source)
    geometry = EzdxfSceneReader().read(source, unit="m").features[0].geometry
    assert geometry.equals(Polygon([(-2, 3), (-8, 3), (-8, 9), (-2, 9)]))


@pytest.mark.parametrize(("sx", "sy", "angle"), [(-1, 1, 0), (1, -1, 37), (-2, 0.5, 123)])
def test_mirrored_block_polyline_uses_world_frame(
    tmp_path: Path,
    sx: float,
    sy: float,
    angle: float,
) -> None:
    local = [(2, 3), (8, 3), (8, 9), (2, 9)]
    doc = ezdxf.new()
    block = doc.blocks.new("arbitrary")
    block.add_lwpolyline(local, close=True)
    doc.modelspace().add_blockref(
        "arbitrary",
        (120, 240),
        dxfattribs={"xscale": sx, "yscale": sy, "rotation": angle},
    )
    source = tmp_path / "mirror.dxf"
    doc.saveas(source)
    theta = math.radians(angle)
    expected = Polygon(
        [
            (
                120 + sx * x * math.cos(theta) - sy * y * math.sin(theta),
                240 + sx * x * math.sin(theta) + sy * y * math.cos(theta),
            )
            for x, y in local
        ]
    )
    geometry = EzdxfSceneReader().read(source, unit="m").features[0].geometry
    assert geometry.hausdorff_distance(expected) < 1e-9


@pytest.mark.parametrize("layer", ["0", "anon-X9", "Водопровод", "Тротуар"])
@pytest.mark.parametrize("radius", [0.2, 1.7, 4.0])
def test_circle_size_and_name_do_not_erase_its_area(
    tmp_path: Path,
    layer: str,
    radius: float,
) -> None:
    doc = ezdxf.new()
    if layer != "0":
        doc.layers.add(layer)
    doc.modelspace().add_circle(
        (10, 20),
        radius,
        dxfattribs={"layer": layer, "extrusion": (0, 0, -1)},
    )
    source = tmp_path / "circle.dxf"
    doc.saveas(source)
    feature = EzdxfSceneReader(flatten_distance_m=0.001).read(source, unit="m").features[0]
    assert feature.geometry.geom_type == "Polygon"
    assert feature.geometry.area == pytest.approx(math.pi * radius**2, rel=0.01)
    assert (feature.geometry.centroid.x, feature.geometry.centroid.y) == pytest.approx((-10, 20))
    assert feature.circle_radius_m == radius


def test_text_ocs_and_mtext_wcs_are_not_confused(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.modelspace().add_text("ГАЗОН", dxfattribs={"insert": (10, 20), "extrusion": (0, 0, -1)})
    doc.modelspace().add_mtext("А", dxfattribs={"insert": (30, 40), "extrusion": (0, 0, -1)})
    source = tmp_path / "labels.dxf"
    doc.saveas(source)
    labels = EzdxfSceneReader().read(source, unit="m").labels
    assert [(label.x, label.y) for label in labels] == [(-10, 20), (30, 40)]


def test_attached_attributes_are_evidence_in_each_array_instance(tmp_path: Path) -> None:
    doc = ezdxf.new()
    symbol = doc.blocks.new("arbitrary")
    symbol.add_point((0, 0))
    symbol.add_attdef("MATERIAL", (1, 2), "")
    insert = doc.modelspace().add_blockref(
        "arbitrary",
        (100, 200),
        dxfattribs={"column_count": 2, "column_spacing": 20},
    )
    insert.add_auto_attribs({"MATERIAL": "ГАЗОН"})
    source = tmp_path / "attributes.dxf"
    doc.saveas(source)
    labels = EzdxfSceneReader().read(source, unit="m").labels
    assert sorted((label.x, label.y, label.text) for label in labels) == [
        (101, 202, "ГАЗОН"),
        (121, 202, "ГАЗОН"),
    ]
    assert len({str(label.ref) for label in labels}) == 2


def test_tilted_elevated_polyline_projects_world_xy(tmp_path: Path) -> None:
    doc = ezdxf.new()
    local = [(2, 3), (8, 3), (8, 9), (2, 9)]
    doc.modelspace().add_lwpolyline(
        local, close=True, dxfattribs={"extrusion": (0, 1, 1), "elevation": 7}
    )
    source = tmp_path / "tilted.dxf"
    doc.saveas(source)
    geometry = EzdxfSceneReader().read(source, unit="m").features[0].geometry
    expected = Polygon([(-x, (7 - y) / math.sqrt(2)) for x, y in local])
    assert geometry.hausdorff_distance(expected) < 1e-9


def test_only_tree_semantics_turns_a_circle_into_a_trunk_position(tmp_path: Path) -> None:
    doc = ezdxf.new()
    for layer in ("Полоса деревьев", "Тротуар", "Газон"):
        doc.layers.add(layer)
        doc.modelspace().add_circle((10, 20), 0.7, dxfattribs={"layer": layer})
    source = tmp_path / "semantic-circles.dxf"
    doc.saveas(source)
    raw: Scene = EzdxfSceneReader().read(source, unit="m")
    assert all(f.geometry.geom_type == "Polygon" for f in raw.features)
    layer_map = YamlLayerMapSource(
        Path(__file__).resolve().parents[1] / "config/layer_map.yaml"
    ).load()
    scene, _ = classify_scene(raw, layer_map)
    by_class = {f.object_class: f.geometry for f in scene.features}
    assert by_class[ObjectClass.EXISTING_TREE].geom_type == "Point"
    assert by_class[ObjectClass.SIDEWALK].area > 1.5
    assert by_class[ObjectClass.LAWN].area > 1.5
