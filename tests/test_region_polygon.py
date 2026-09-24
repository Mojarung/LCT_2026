"""A REGION is usable only when its complete planar contour is established."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.acis import api
from ezdxf.render import MeshBuilder
from shapely.geometry import box

from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("version", ["R2010", "R2018"])
@pytest.mark.parametrize(("scale", "units"), [(1, 6), (1000, 4)])
def test_one_horizontal_straight_face_is_an_exact_polygon(
    tmp_path: Path, version: str, scale: int, units: int
) -> None:
    doc = ezdxf.new(version)
    doc.header["$INSUNITS"] = units
    mesh = MeshBuilder()
    mesh.add_face(
        [
            (10 * scale, 20 * scale, 3 * scale),
            (14 * scale, 20 * scale, 3 * scale),
            (14 * scale, 23 * scale, 3 * scale),
            (10 * scale, 23 * scale, 3 * scale),
        ]
    )
    entity = doc.modelspace().add_region(dxfattribs={"layer": "anonymous ground"})
    api.export_dxf(entity, [api.body_from_mesh(mesh)])
    path = tmp_path / "ground.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path)
    require_complete_geometry(scene)
    assert len(scene.features) == 1
    feature = scene.features[0]
    assert feature.source_entity_type == "REGION"
    assert feature.layer == "anonymous ground"
    expected = box(10, 20, 14, 23)
    assert feature.geometry.symmetric_difference(expected).area < 1e-8
    assert feature.geometry.hausdorff_distance(expected) < 1e-8
    assert feature.geometry_error_m == 0


@pytest.mark.parametrize(
    "faces",
    [
        [[(0, 0, 0), (4, 0, 0), (4, 3, 1), (0, 3, 1)]],
        [
            [(0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)],
            [(6, 0, 0), (8, 0, 0), (8, 3, 0), (6, 3, 0)],
        ],
    ],
)
def test_tilted_or_multiface_region_remains_a_gap(
    tmp_path: Path, faces: list[list[tuple[int, int, int]]]
) -> None:
    doc = ezdxf.new("R2018")
    mesh = MeshBuilder()
    for face in faces:
        mesh.add_face(face)
    region = doc.modelspace().add_region()
    api.export_dxf(region, [api.body_from_mesh(mesh)])
    path = tmp_path / "unsupported.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    with pytest.raises(InputError, match="REGION"):
        require_complete_geometry(scene)
    assert scene.read_diagnostics.geometry_gaps[0].count == 1


def test_nested_and_reflected_regions_keep_insert_coordinates(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    leaf = doc.blocks.new("leaf")
    mesh = MeshBuilder()
    mesh.add_face([(0, 0, 0), (4, 0, 0), (4, 3, 0), (0, 3, 0)])
    region = leaf.add_region()
    api.export_dxf(region, [api.body_from_mesh(mesh)])
    wrapper = doc.blocks.new("wrapper")
    wrapper.add_blockref("leaf", (5, 0))
    doc.modelspace().add_blockref("wrapper", (100, 200), dxfattribs={"rotation": 30})
    doc.modelspace().add_blockref("wrapper", (100, 200), dxfattribs={"xscale": -1})
    path = tmp_path / "nested.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path, unit="m")
    require_complete_geometry(scene)
    assert len(scene.features) == 2
    assert len({feature.ref for feature in scene.features}) == 2
    rotated, reflected = (feature.geometry for feature in scene.features)
    first_x = 100 + 5 * math.cos(math.radians(30))
    first_y = 200 + 5 * math.sin(math.radians(30))
    assert rotated.exterior.coords[0] == pytest.approx((first_x, first_y))
    assert reflected.bounds == pytest.approx((91, 200, 95, 203))


def test_region_in_minsert_has_one_feature_per_instance(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("region sign")
    mesh = MeshBuilder()
    mesh.add_face([(0, 0, 0), (2, 0, 0), (2, 1, 0), (0, 1, 0)])
    region = block.add_region()
    api.export_dxf(region, [api.body_from_mesh(mesh)])
    doc.modelspace().add_blockref(
        block.name,
        (10, 20),
        dxfattribs={
            "row_count": 2,
            "column_count": 2,
            "row_spacing": 5,
            "column_spacing": 4,
        },
    )
    path = tmp_path / "array.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path, unit="m")
    require_complete_geometry(scene)
    assert len(scene.features) == 4
    assert len({feature.ref for feature in scene.features}) == 4
    assert {feature.geometry.bounds for feature in scene.features} == {
        (10, 20, 12, 21),
        (14, 20, 16, 21),
        (10, 25, 12, 26),
        (14, 25, 16, 26),
    }
