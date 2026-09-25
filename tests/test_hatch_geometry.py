"""HATCH areas must preserve every loop and have a bounded curve error."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import numpy as np
import pytest
import shapely
from shapely.geometry import Point, box

from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.entities import Hatch

    from green.domain.objects import Scene


def read(doc: Drawing, tmp_path: Path) -> Scene:
    source = tmp_path / "hatch.dxf"
    doc.saveas(source)
    return EzdxfSceneReader().read(source)


def rectangle(hatch: Hatch, bounds: tuple, flags: int = 1, *, reverse: bool = False) -> None:
    points = list(box(*bounds).exterior.coords)
    hatch.paths.add_polyline_path(points[::-1] if reverse else points, flags=flags)


@pytest.mark.parametrize("kind", ["arc", "ellipse", "bulge"])
@pytest.mark.parametrize("scale", [1, 1000])
@pytest.mark.parametrize("normal", [(0, 0, 1), (0, 0, -1), (0, 1, 1)])
def test_hatch_curves_have_native_distance_bound(
    tmp_path: Path, kind: str, scale: int, normal: tuple
) -> None:
    doc = ezdxf.new()
    doc.units = 6 if scale == 1 else 4
    hatch = doc.modelspace().add_hatch(dxfattribs={"extrusion": normal, "elevation": (0, 0, 7)})
    radius = 100 * scale
    ratio = 0.03 if kind == "ellipse" else 1
    if kind == "bulge":
        hatch.paths.add_polyline_path([(radius, 0, 1), (-radius, 0, 1)])
    else:
        path = hatch.paths.add_edge_path()
        if kind == "arc":
            path.add_arc((0, 0), radius)
        else:
            path.add_ellipse((0, 0), (radius, 0), ratio)
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    feature = scene.features[0]
    assert feature.geometry_error_m is not None
    assert 0 < feature.geometry_error_m <= 0.100001
    native = [
        hatch.ocs().to_wcs((radius * math.cos(a), radius * ratio * math.sin(a), 7))
        for a in np.linspace(0, math.tau, 5001)
    ]
    points = shapely.points([(v.x / scale, v.y / scale) for v in native])
    assert shapely.distance(points, feature.geometry.boundary).max() <= feature.geometry_error_m


@pytest.mark.parametrize("kind", ["arc", "ellipse"])
@pytest.mark.parametrize("ccw", [True, False])
def test_clockwise_edge_path_closes_without_an_invented_chord(
    tmp_path: Path, kind: str, *, ccw: bool
) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    path = hatch.paths.add_edge_path()
    if kind == "arc":
        edge = path.add_arc((0, 0), 10, 0, 180, ccw=ccw)
    else:
        edge = path.add_ellipse((0, 0), (10, 0), 0.4, 0, 180, ccw=ccw)
    path.add_line(edge.real_end_point, edge.real_start_point)
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    area = scene.features[0].geometry
    assert area.covers(Point(0, 1))
    assert not area.covers(Point(0, -1))


@pytest.mark.parametrize("style", [0, 1, 2])
def test_multiple_external_areas_are_kept_for_each_hatch_style(tmp_path: Path, style: int) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    hatch.dxf.hatch_style = style
    rectangle(hatch, (0, 0, 10, 10))
    rectangle(hatch, (20, 0, 30, 10))
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    assert scene.features[0].geometry.equals(box(0, 0, 10, 10).union(box(20, 0, 30, 10)))


@pytest.mark.parametrize("offset", [(10, 0), (10, 10)])
def test_adjacent_hatch_rings_share_only_a_boundary(tmp_path: Path, offset: tuple) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    hatch.dxf.hatch_style = 1
    rectangle(hatch, (0, 0, 10, 10))
    rectangle(hatch, (offset[0], offset[1], offset[0] + 10, offset[1] + 10))
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    expected = box(0, 0, 10, 10).union(box(offset[0], offset[1], offset[0] + 10, offset[1] + 10))
    assert scene.features[0].geometry.equals(expected)
    assert scene.features[0].geometry.area == pytest.approx(200)


def test_nested_ring_touching_outer_boundary_is_rejected(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    rectangle(hatch, (0, 0, 10, 10))
    rectangle(hatch, (0, 4, 4, 6), flags=16)
    scene = read(doc, tmp_path)
    with pytest.raises(InputError, match="hatch-intersecting-boundaries"):
        require_complete_geometry(scene)


def test_adjacent_rings_with_floating_point_overlap_are_unioned(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    rectangle(hatch, (0, 0, 10, 10))
    rectangle(hatch, (math.nextafter(10, 0), 0, 20, 10))
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    assert scene.features[0].geometry.hausdorff_distance(box(0, 0, 20, 10)) < 1e-12
    assert scene.features[0].geometry.area == pytest.approx(200)


@pytest.mark.parametrize(
    ("style", "expected"),
    [
        (0, [True, False, True, False]),
        (1, [True, False, False, False]),
        (2, [True, True, True, True]),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_nested_islands_respect_style_and_ignore_vertex_winding(
    tmp_path: Path, style: int, expected: list[bool], *, reverse: bool
) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    hatch.dxf.hatch_style = style
    # Add in a non-spatial order; external/outermost/default flags only filter paths.
    for inset, flags in [(4, 0), (0, 1), (6, 0), (2, 16)]:
        rectangle(hatch, (inset, inset, 20 - inset, 20 - inset), flags, reverse=reverse)
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    area = scene.features[0].geometry
    assert [area.covers(Point(i, 10)) for i in (1, 3, 5, 7)] == expected


@pytest.mark.parametrize("kind", ["edge_gap", "open_polyline", "crossing_loops"])
def test_ambiguous_boundaries_cannot_silently_become_plantable_area(
    tmp_path: Path, kind: str
) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    if kind == "edge_gap":
        path = hatch.paths.add_edge_path()
        path.add_line((0, 0), (10, 0))
        path.add_line((10, 2), (10, 10))
        path.add_line((10, 10), (0, 10))
        path.add_line((0, 10), (0, 0))
    elif kind == "open_polyline":
        hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10)], is_closed=False)
    else:
        rectangle(hatch, (0, 0, 10, 10))
        rectangle(hatch, (5, 5, 15, 15))
    scene = read(doc, tmp_path)
    with pytest.raises(InputError):
        require_complete_geometry(scene)


def test_open_flag_with_explicitly_closed_vertices_is_accepted(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 0)], is_closed=False)
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    assert scene.features[0].geometry.area == 50


def test_millimetre_seam_is_closed_with_reported_error(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.001)], is_closed=False)
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    feature = scene.features[0]
    assert feature.geometry.area == pytest.approx(100)
    assert feature.geometry_error_m is not None
    assert feature.geometry_error_m >= 0.001


def test_large_curve_tolerance_does_not_close_centimetre_seam(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.units = 6
    hatch = doc.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0.01)], is_closed=False)
    source = tmp_path / "open.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader(flatten_distance_m=10).read(source)
    with pytest.raises(InputError, match="HATCH"):
        require_complete_geometry(scene)


@pytest.mark.parametrize("start", [11.1, 40.1, -45.1, 355.9])
@pytest.mark.parametrize("kind", ["HATCH", "ARC"])
@pytest.mark.parametrize("end_shift", [-math.inf, math.inf])
def test_full_turn_does_not_collapse_after_angle_normalization(
    tmp_path: Path, start: float, kind: str, end_shift: float
) -> None:
    doc = ezdxf.new()
    doc.units = 6
    end = math.nextafter(start + 360, end_shift)
    if kind == "HATCH":
        doc.modelspace().add_hatch().paths.add_edge_path().add_arc((0, 0), 100, start, end)
    else:
        doc.modelspace().add_arc((0, 0), 100, start, end)
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    geometry = scene.features[0].geometry
    assert geometry.length > 620
    if kind == "HATCH":
        assert geometry.area > 31_000


def test_tiny_arc_is_not_treated_as_a_full_turn(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.units = 6
    doc.modelspace().add_arc((0, 0), 100, 11.1, 11.10000001)
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    assert scene.features[0].geometry.length < 1e-6


@pytest.mark.parametrize("field", ["offset_vector", "degenerated_loops"])
def test_mpolygon_unimplemented_spatial_modifiers_are_explicit(tmp_path: Path, field: str) -> None:
    doc = ezdxf.new()
    doc.units = 6
    entity = doc.modelspace().add_mpolygon()
    entity.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)])
    entity.dxf.set(field, (2, 3) if field == "offset_vector" else 1)
    scene = read(doc, tmp_path)
    with pytest.raises(InputError, match="mpolygon"):
        require_complete_geometry(scene)


def test_basic_mpolygon_keeps_its_hole(tmp_path: Path) -> None:
    doc = ezdxf.new()
    doc.units = 6
    entity = doc.modelspace().add_mpolygon()
    entity.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], flags=1)
    entity.paths.add_polyline_path([(2, 2), (8, 2), (8, 8), (2, 8)], flags=16)
    scene = read(doc, tmp_path)
    require_complete_geometry(scene)
    assert scene.features[0].geometry.area == 64
