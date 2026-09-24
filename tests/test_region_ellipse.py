"""A curved ACIS REGION is read only when its complete contour is verifiable."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.acis import api
from ezdxf.render import MeshBuilder
from shapely.geometry import Point

from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.layouts import BaseLayout


def _curved_region(
    layout: BaseLayout, *, ratio: float = 1.0, normal_z: int = 1, name: str = "ellipse-curve"
) -> None:
    mesh = MeshBuilder()
    mesh.add_face([(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)])
    region = layout.add_region()
    api.export_dxf(region, [api.body_from_mesh(mesh)])
    sat = list(region.sat)
    index = next(index for index, record in enumerate(sat) if "straight-curve" in record)
    # The mesh's first local edge runs (-1,-1) -> (1,-1); the replacement is
    # a lower half ellipse. The body's existing (1,1) transform puts it at y=0.
    sat[index] = f"{name} $-1 -1 $-1 0 -1 0 0 0 {normal_z} 1 0 0 {ratio} I I #"
    region.sat = sat


@pytest.mark.parametrize(("ratio", "normal_z"), [(1.0, 1), (0.5, 1), (1.0, -1)])
def test_sat_ellipse_region_has_bounded_contour(
    tmp_path: Path, ratio: float, normal_z: int
) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    _curved_region(doc.modelspace(), ratio=ratio, normal_z=normal_z)
    source = tmp_path / "curved.dxf"
    doc.saveas(source)

    scene = EzdxfSceneReader().read(source)
    require_complete_geometry(scene)
    assert len(scene.features) == 1
    feature = scene.features[0]
    assert feature.source_entity_type == "REGION"
    assert feature.geometry_error_m is not None
    assert 0 < feature.geometry_error_m < 0.02
    assert abs(feature.geometry.area - (4 + normal_z * math.pi * ratio / 2)) < 0.04
    # The true arc's apex may lie outside the polygon; the stated error must
    # cover its distance from the sampled boundary.
    apex = Point(1, -normal_z * ratio)
    assert feature.geometry.boundary.distance(apex) <= feature.geometry_error_m + 1e-9


def test_sat_ellipse_region_in_reflected_nonuniform_insert(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    block = doc.blocks.new("anonymous")
    _curved_region(block)
    doc.modelspace().add_blockref(
        block.name, (100, 200), dxfattribs={"xscale": -2, "yscale": 1.5}
    )
    source = tmp_path / "nested-curved.dxf"
    doc.saveas(source)

    scene = EzdxfSceneReader().read(source)
    require_complete_geometry(scene)
    assert len(scene.features) == 1
    feature = scene.features[0]
    assert feature.geometry.bounds == pytest.approx((96, 198.5, 100, 203), abs=0.03)
    assert abs(feature.geometry.area - 3 * (4 + math.pi / 2)) < 0.12
    assert feature.geometry_error_m is not None
    assert 0 < feature.geometry.boundary.distance(Point(98, 198.5)) <= feature.geometry_error_m


@pytest.mark.parametrize(
    ("name", "ratio"),
    [("spline-curve", 1.0), ("ellipse-curve", 2.0)],
)
def test_unknown_or_invalid_sat_curve_remains_gap(tmp_path: Path, name: str, ratio: float) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    _curved_region(doc.modelspace(), ratio=ratio, name=name)
    source = tmp_path / "unreadable.dxf"
    doc.saveas(source)

    scene = EzdxfSceneReader().read(source)
    with pytest.raises(InputError, match="REGION"):
        require_complete_geometry(scene)
    assert len(scene.features) == 0
    assert scene.read_diagnostics.geometry_gaps[0].count == 1


def test_sat_region_with_broken_coedge_back_link_remains_gap(tmp_path: Path) -> None:
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6
    _curved_region(doc.modelspace())
    region = doc.modelspace().query("REGION")[0]
    sat = list(region.sat)
    index = next(index for index, record in enumerate(sat) if record.startswith("coedge "))
    fields = sat[index].split()
    fields[5] = "$-1"  # sever the previous coedge pointer, leave the forward loop intact
    sat[index] = " ".join(fields)
    region.sat = sat
    source = tmp_path / "broken-loop.dxf"
    doc.saveas(source)

    scene = EzdxfSceneReader().read(source)
    with pytest.raises(InputError, match="REGION"):
        require_complete_geometry(scene)
    assert scene.read_diagnostics.geometry_gaps[0].reason == "acis-loop-open-or-ambiguous"
