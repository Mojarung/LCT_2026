"""A contradictory enclosed surface must not be rescued by label propagation."""

import pytest
import shapely
from shapely.affinity import rotate, translate
from shapely.geometry import Point, box
from test_surface_uncertainty import feature, label

from green.application.surfaces import Material, build_surface_map
from green.domain.objects import ObjectClass


@pytest.mark.parametrize("declared_lawn", [False, True])
@pytest.mark.parametrize(("angle", "offset"), [(0, 0), (37, 100_000)])
def test_hybrid_does_not_reauthorize_a_contradictory_face(
    angle: float, offset: float, *, declared_lawn: bool
) -> None:
    def transform(geometry: shapely.Geometry) -> shapely.Geometry:
        return translate(rotate(geometry, angle, origin=(0, 0)), offset, -offset)

    region = box(0, 0, 30, 20)
    boundary = feature(
        ObjectClass.LAWN if declared_lawn else ObjectClass.CURB,
        transform(region if declared_lawn else region.boundary),
    )
    anchors = [transform(Point(5, 10)), transform(Point(25, 10))]
    surface = build_surface_map(
        [boundary],
        [label(text, p.x, p.y) for text, p in zip(("ГАЗОН", "А"), anchors, strict=True)],
        transform(box(-5, -5, 35, 25)),
        0.5,
        inference_mode="hybrid",
    )
    assert surface is not None
    points = shapely.points([p.coords[0] for p in anchors])
    assert surface.conflicting_faces == 1
    assert surface.material(points).tolist() == [Material.UNKNOWN, Material.UNKNOWN]
    assert not surface.fits_soil(points, 0.5).any()


def test_conflict_does_not_erase_a_separate_unambiguous_lawn() -> None:
    disputed = box(0, 0, 30, 20)
    good = box(40, 0, 60, 20)
    surface = build_surface_map(
        [feature(ObjectClass.CURB, disputed.boundary), feature(ObjectClass.LAWN, good)],
        [label("ГАЗОН", 5, 10), label("А", 25, 10)],
        box(-5, -5, 65, 25),
        0.5,
        inference_mode="hybrid",
    )
    assert surface is not None
    points = shapely.points([(5, 10), (50, 10)])
    assert surface.fits_soil(points, 1.24).tolist() == [False, True]
