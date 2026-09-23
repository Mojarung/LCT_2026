"""Explicit material areas survive unrelated incomplete separator linework."""

from __future__ import annotations

import pytest
import shapely
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, box
from test_surface_uncertainty import feature, label

from green.application.surfaces import Material, build_surface_map
from green.domain.objects import ObjectClass


@pytest.mark.parametrize("angle", [0.0, 21.1994384, 47.5554969])
@pytest.mark.parametrize("offset", [0.0, 100_000.0])
def test_declared_soil_is_not_an_inferred_face(angle: float, offset: float) -> None:
    def transform(shape: shapely.Geometry) -> shapely.Geometry:
        return translate(rotate(shape, angle, origin=(0, 0)), offset, 2 * offset)

    shapes = [
        (ObjectClass.LAWN, box(0, 10, 100, 45)),
        (ObjectClass.ROAD, box(0, 0, 100, 10)),
        (ObjectClass.BUILDING, box(0, 45, 100, 50)),
        (ObjectClass.SIDEWALK, box(40, 10, 45, 45)),
        (ObjectClass.CURB, LineString([(0, 10), (100, 10)])),
        (ObjectClass.CURB, LineString([(20, 10), (55, 40)])),
    ]
    features = [feature(kind, transform(shape), str(i)) for i, (kind, shape) in enumerate(shapes)]
    surface = build_surface_map(features, [], transform(box(0, 0, 100, 50)), 0.5)
    assert surface is not None
    assert surface.soil_area is not None
    assert surface.soil_area.geom_type in {"Polygon", "MultiPolygon"}
    points = shapely.points(
        [transform(Point(x, y)).coords[0] for x, y in [(10, 15), (80, 20), (42, 20), (10, 5)]]
    )
    assert surface.material(points).tolist() == [
        Material.SOIL,
        Material.SOIL,
        Material.PAVED,
        Material.PAVED,
    ]
    assert surface.fits_soil(points, 1.6).tolist() == [True, True, False, False]


def test_paved_label_is_contrary_evidence_even_in_an_unfinished_face() -> None:
    features = [
        feature(ObjectClass.LAWN, box(0, 0, 30, 20), "soil"),
        feature(ObjectClass.CURB, LineString([(10, 0), (10, 8)]), "unfinished"),
    ]
    surface = build_surface_map(features, [label("А", 20, 10)], box(-2, -2, 32, 22), 0.5)
    assert surface is not None
    assert surface.material(shapely.points([(20, 10)])).tolist() == [Material.UNKNOWN]
    assert not surface.fits_soil(shapely.points([(20, 10)]), 1.6)[0]


def test_explicit_soil_hole_stays_unknown_with_unfinished_lines() -> None:
    soil = box(0, 0, 30, 20).difference(box(15, 5, 25, 15))
    surface = build_surface_map(
        [feature(ObjectClass.LAWN, soil), feature(ObjectClass.CURB, LineString([(5, 0), (5, 8)]))],
        [],
        box(-2, -2, 32, 22),
        0.5,
    )
    assert surface is not None
    assert surface.material(shapely.points([(20, 10)])).tolist() == [Material.UNKNOWN]
    assert surface.material(shapely.points([(10, 10)])).tolist() == [Material.SOIL]


@pytest.mark.parametrize("extent", [box(30, 0, 40, 20), box(30, 20, 40, 30)])
def test_touching_a_lawn_does_not_create_positive_soil(extent: shapely.Geometry) -> None:
    surface = build_surface_map([feature(ObjectClass.LAWN, box(0, 0, 30, 20))], [], extent, 0.5)
    assert surface is not None
    assert surface.soil_area is None
    assert not surface.fits_soil(shapely.points([(30, 10), (30, 20), (35, 10)]), 1.6).any()
