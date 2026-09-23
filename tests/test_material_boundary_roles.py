"""A topological enclosure is not necessarily a boundary of ground material."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, box
from test_surface_uncertainty import feature, label, material

from green.application.surfaces import Material, build_surface_map
from green.domain.objects import ObjectClass


@pytest.mark.parametrize(
    "kind",
    [
        ObjectClass.FENCE,
        ObjectClass.ROAD,
        ObjectClass.SIDEWALK,
        ObjectClass.TRAM,
        ObjectClass.RAILWAY,
        ObjectClass.BUILDING,
    ],
)
def test_closed_nonmaterial_lines_do_not_authorize_soil(kind: ObjectClass) -> None:
    # Separate lines may be axes, rails, walls or an enclosure. Their class does
    # not establish which side, if any, is homogeneous soil.
    ring = box(0, 0, 20, 20).exterior.coords
    features = [feature(kind, LineString([ring[i], ring[i + 1]]), str(i)) for i in range(4)]
    surface = build_surface_map(features, [label("ГАЗОН", 5, 5)], box(-5, -5, 25, 25), 0.5)
    assert material(surface, 10, 10) is Material.UNKNOWN
    assert surface is not None
    assert surface.unsupported_boundary_faces == 1


def test_fence_cannot_complete_an_unfinished_curb() -> None:
    features = [
        feature(ObjectClass.CURB, LineString([(0, 0), (0, 20), (20, 20), (20, 0)])),
        feature(ObjectClass.FENCE, LineString([(0, 0), (20, 0)]), "fence"),
    ]
    surface = build_surface_map(features, [label("ГАЗОН", 5, 5)], box(-5, -5, 25, 25), 0.5)
    assert material(surface, 10, 10) is Material.UNKNOWN


def test_inner_fence_preserves_unknown_hole_without_erasing_outer_lawn() -> None:
    features = [
        feature(ObjectClass.CURB, box(0, 0, 30, 30).boundary),
        feature(ObjectClass.FENCE, box(10, 10, 20, 20).boundary, "fence"),
    ]
    surface = build_surface_map(
        features, [label("ГАЗОН", 5, 5), label("ГАЗОН", 12, 12)], box(-5, -5, 35, 35), 0.5
    )
    assert material(surface, 5, 5) is Material.SOIL
    assert material(surface, 15, 15) is Material.UNKNOWN


def test_shared_fence_and_material_edge_keeps_actual_material_evidence() -> None:
    features = [
        feature(ObjectClass.CURB, box(0, 0, 20, 20).boundary),
        feature(ObjectClass.FENCE, box(0, 0, 20, 20).boundary, "fence"),
    ]
    surface = build_surface_map(features, [label("ГАЗОН", 5, 5)], box(-5, -5, 25, 25), 0.5)
    assert material(surface, 10, 10) is Material.SOIL


def test_fence_divider_preserves_material_ambiguity_on_both_sides() -> None:
    features = [
        feature(ObjectClass.CURB, box(0, 0, 20, 20).boundary),
        feature(ObjectClass.FENCE, LineString([(10, 0), (10, 20)]), "fence"),
    ]
    surface = build_surface_map(features, [label("ГАЗОН", 5, 5)], box(-5, -5, 25, 25), 0.5)
    assert material(surface, 5, 5) is Material.UNKNOWN
    assert material(surface, 15, 5) is Material.UNKNOWN


def test_hard_surface_area_keeps_negative_evidence_without_labels() -> None:
    road = feature(ObjectClass.ROAD, box(0, 0, 20, 20))
    surface = build_surface_map([road], [], box(-5, -5, 25, 25), 0.5)
    assert material(surface, 10, 10) is Material.PAVED
