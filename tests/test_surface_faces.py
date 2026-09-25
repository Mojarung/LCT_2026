"""A material label needs a closed material boundary, not merely a nearby point."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
import shapely
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, box
from test_surface_uncertainty import feature, label, material

from green.application.surface_faces import _roundoff_grid
from green.application.surfaces import Material, build_surface_map
from green.domain.objects import ObjectClass


def test_unbounded_label_does_not_turn_nearby_blank_space_into_soil() -> None:
    surface = build_surface_map([], [label("ГАЗОН", 5, 5)], box(0, 0, 20, 20), 0.5)
    assert material(surface, 7, 5) is Material.UNKNOWN


def test_project_boundary_does_not_close_a_material_region() -> None:
    boundary = feature(ObjectClass.WORK_BOUNDARY, box(0, 0, 20, 20))
    curb = feature(ObjectClass.CURB, LineString([(0, 10), (20, 10)]))
    surface = build_surface_map([boundary, curb], [label("ГАЗОН", 5, 5)], boundary.geometry, 0.5)
    assert material(surface, 7, 5) is Material.UNKNOWN


def test_tree_in_a_grate_does_not_establish_surrounding_soil() -> None:
    tree = feature(ObjectClass.EXISTING_TREE, Point(5, 5))
    surface = build_surface_map([tree], [], box(0, 0, 20, 20), 0.5)
    assert surface is None or material(surface, 5.1, 5.1) is Material.UNKNOWN


def test_paved_only_input_has_no_soil_and_does_not_crash() -> None:
    sidewalk = feature(ObjectClass.SIDEWALK, box(0, 0, 10, 10))
    surface = build_surface_map([sidewalk], [], box(0, 0, 20, 20), 0.5)
    assert surface is not None
    assert surface.soil_area is None
    assert material(surface, 5, 5) is Material.PAVED
    assert material(surface, 15, 15) is Material.UNKNOWN


def test_two_conflicting_labels_do_not_split_one_material_region_by_distance() -> None:
    border = feature(ObjectClass.PAVEMENT_EDGE, box(0, 0, 100, 20).boundary)
    surface = build_surface_map(
        [border], [label("ГАЗОН", 5, 10), label("А", 95, 10)], box(-5, -5, 105, 25), 0.5
    )
    assert material(surface, 6, 10) is Material.UNKNOWN
    assert material(surface, 94, 10) is Material.UNKNOWN


def test_unclosed_curb_gap_does_not_create_a_soil_region() -> None:
    border = feature(ObjectClass.CURB, LineString([(0, 1), (0, 20), (20, 20), (20, 0), (1, 0)]))
    surface = build_surface_map([border], [label("ГАЗОН", 5, 5)], box(-5, -5, 25, 25), 0.5)
    assert material(surface, 7, 5) is Material.UNKNOWN


@pytest.mark.parametrize("angle", [0, 23, 91])
@pytest.mark.parametrize("offset", [0, 1_000_000])
def test_closed_material_faces_preserve_holes_and_transforms(angle: float, offset: float) -> None:
    outer, hole = box(0, 0, 100, 40).boundary, box(40, 10, 60, 30).boundary

    def transform(geometry: shapely.Geometry) -> shapely.Geometry:
        return translate(rotate(geometry, angle, origin=(0, 0)), offset, -offset)

    features = [
        feature(ObjectClass.CURB, transform(g), str(i)) for i, g in enumerate([outer, hole])
    ]
    anchor = transform(Point(5, 5))
    soil_label = label("ГАЗОН", anchor.x, anchor.y)
    extent = transform(box(-5, -5, 105, 45))
    surface = build_surface_map(features, [soil_label], extent, 0.5)
    assert surface is not None
    points = shapely.points(
        [transform(Point(x, y)).coords[0] for x, y in [(90, 35), (50, 20), (-2, 5)]]
    )
    assert surface.material(points).tolist() == [Material.SOIL, Material.UNKNOWN, Material.UNKNOWN]
    assert surface.fits_soil(points[:1], 1.6).tolist() == [True]


def test_label_in_curve_uncertainty_band_cannot_assign_either_face() -> None:
    border = replace(feature(ObjectClass.CURB, box(0, 0, 20, 20).boundary), geometry_error_m=0.2)
    surface = build_surface_map([border], [label("ГАЗОН", 0.1, 10)], box(-5, -5, 25, 25), 0.5)
    assert material(surface, 5, 10) is Material.UNKNOWN


def test_straight_polygonized_edges_assign_adjacent_regions_without_leakage() -> None:
    lines = [box(0, 0, 20, 10).boundary, LineString([(10, 0), (10, 10)])]
    features = [feature(ObjectClass.PAVEMENT_EDGE, g, str(i)) for i, g in enumerate(lines)]
    surface = build_surface_map(
        features, [label("ГАЗОН", 5, 5), label("А", 15, 5)], box(-5, -5, 25, 15), 0.5
    )
    assert material(surface, 5, 5) is Material.SOIL
    assert material(surface, 15, 5) is Material.PAVED
    assert material(surface, 22, 5) is Material.UNKNOWN


def test_shared_edge_survives_independent_rotation_at_large_cad_coordinates() -> None:
    def transformed(geometry: shapely.Geometry) -> shapely.Geometry:
        return translate(rotate(geometry, 23, origin=(0, 0)), 1_000_000, -1_000_000)

    outer = transformed(box(0, 0, 100, 40).boundary)
    divider = transformed(LineString([(50, 0), (50, 40)]))
    soil = transformed(Point(5, 5))
    paved = transformed(Point(95, 5))
    expected = [Material.SOIL, Material.PAVED]
    surface = build_surface_map(
        [feature(ObjectClass.CURB, outer), feature(ObjectClass.PAVEMENT_EDGE, divider)],
        [label("ГАЗОН", soil.x, soil.y), label("А", paved.x, paved.y)],
        transformed(box(-5, -5, 105, 45)),
        0.5,
    )
    probes = shapely.points([transformed(Point(x, 5)).coords[0] for x in (7, 90)])
    assert surface is not None
    assert surface.material(probes).tolist() == expected


@pytest.mark.parametrize("gap_m", [1e-5, 1e-8, 1e-9])
def test_visible_divider_gap_stays_open_at_large_cad_coordinates(gap_m: float) -> None:
    offset = 1_000_000
    outer = feature(ObjectClass.CURB, translate(box(0, 0, 20, 10).boundary, offset, 0))
    divider = feature(
        ObjectClass.PAVEMENT_EDGE,
        LineString([(offset + 10, 0), (offset + 10, 10 - gap_m)]),
    )
    surface = build_surface_map(
        [outer, divider],
        [label("ГАЗОН", offset + 5, 5)],
        translate(box(-5, -5, 25, 15), offset, 0),
        0.5,
    )
    assert material(surface, offset + 5, 5) is Material.UNKNOWN


def test_roundoff_grid_disables_snapping_when_coordinates_are_too_large() -> None:
    line = LineString([(1e12, 0), (1e12 + 10, 10)])
    assert _roundoff_grid(np.array([line], dtype=object)) == 0.0
    degenerate = LineString([(0, 0), (0, 0)])
    assert _roundoff_grid(np.array([degenerate], dtype=object)) == 0.0


def test_unfinished_internal_boundary_does_not_authorize_the_whole_outer_face() -> None:
    features = [
        feature(ObjectClass.CURB, box(0, 0, 20, 10).boundary, "outer"),
        feature(ObjectClass.CURB, LineString([(10, 0), (10, 8)]), "unfinished"),
    ]
    surface = build_surface_map(features, [label("ГАЗОН", 5, 5)], box(-5, -5, 25, 15), 0.5)
    assert material(surface, 15, 5) is Material.UNKNOWN


def test_conflicting_labels_also_require_review_of_a_named_lawn_polygon() -> None:
    features = [feature(ObjectClass.LAWN, box(0, 0, 20, 10))]
    surface = build_surface_map(
        features, [label("ГАЗОН", 5, 5), label("А", 15, 5)], box(-5, -5, 25, 15), 0.5
    )
    assert material(surface, 5, 5) is Material.UNKNOWN


def test_external_dangling_line_touching_the_border_does_not_invalidate_the_face() -> None:
    features = [
        feature(ObjectClass.CURB, box(0, 0, 20, 10).boundary, "outer"),
        feature(ObjectClass.CURB, LineString([(10, 0), (10, -8)]), "outside"),
    ]
    surface = build_surface_map(features, [label("ГАЗОН", 5, 5)], box(-5, -10, 25, 15), 0.5)
    assert material(surface, 15, 5) is Material.SOIL
