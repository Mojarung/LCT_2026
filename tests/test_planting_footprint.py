"""Counterexamples where a permitted centre does not certify its surrounding area."""

from __future__ import annotations

import numpy as np
import pytest
import shapely
from shapely.geometry import LineString, box

from green.application.constraints import ConstraintIndex
from green.application.surfaces import Material, SurfaceMap, build_surface_map
from green.application.zones import build_zones
from green.domain.norms import (
    Citation,
    CitationStatus,
    DistanceRule,
    MeasureTo,
    PlantingType,
    Severity,
)
from green.domain.objects import Feature, ObjectClass, SourceRef


def feature(cls: ObjectClass, geom: shapely.Geometry) -> Feature:
    return Feature(
        SourceRef("00000000", "00000000", cls.value), "arbitrary", geom, object_class=cls
    )


@pytest.mark.parametrize("cell", [0.25, 0.5, 1.0])
def test_exact_lawn_edge_is_not_expanded_to_raster_cell(cell: float) -> None:
    lawn = box(0.13, 0.13, 10.13, 10.13)
    surface = build_surface_map([feature(ObjectClass.LAWN, lawn)], [], box(-1, -1, 12, 12), cell)
    assert surface is not None
    # Both points can share a raster cell, but only one is inside the polygon.
    got = surface.material(shapely.points([(10.12, 5), (10.14, 5)]))
    assert got[0] == Material.SOIL
    assert got[1] != Material.SOIL


@pytest.mark.parametrize("obstacle", [ObjectClass.WORK_BOUNDARY, ObjectClass.SIDEWALK])
def test_footprint_cannot_cross_an_exact_boundary(obstacle: ObjectClass) -> None:
    geom = box(0, 0, 10, 10) if obstacle is ObjectClass.WORK_BOUNDARY else box(-10, 0, 0, 10)
    index = ConstraintIndex(
        [feature(obstacle, geom)], [], require_utility_data=False, planting_radius_m=0.5
    )
    assert index.plantable(shapely.points([(0.2, 5), (0.6, 5)])).tolist() == [False, True]


def test_small_hole_in_lawn_cannot_be_lost_between_raster_centres() -> None:
    lawn = box(0, 0, 10, 10).difference(box(5.01, 5.01, 5.09, 5.09))
    surface = build_surface_map([feature(ObjectClass.LAWN, lawn)], [], box(0, 0, 10, 10), 1)
    assert surface is not None
    index = ConstraintIndex(
        [], [], require_utility_data=False, surface=surface, planting_radius_m=0.5
    )
    assert index.plantable(shapely.points([(5.05, 5.05), (5.3, 5.3), (3, 3)])).tolist() == [
        False,
        False,
        True,
    ]


def test_inferred_soil_footprint_bound_is_conservative_against_exact_cell_union() -> None:
    rng = np.random.default_rng(541)
    for _ in range(6):
        grid = np.where(rng.random((14, 17)) > 0.15, Material.SOIL, Material.UNKNOWN).astype(
            np.int8
        )
        surface = SurfaceMap(grid, (3.13, -7.09), 0.7, 0, 1)
        rows, cols = np.nonzero(grid == Material.SOIL)
        x, y = 3.13 + cols * 0.7, -7.09 + rows * 0.7
        # Adjacent cells must share identical floating-point vertices. Computing
        # x+cell independently creates microscopic cracks in the oracle itself.
        exact = shapely.union_all(
            shapely.box(x, y, 3.13 + (cols + 1) * 0.7, -7.09 + (rows + 1) * 0.7)
        )
        points = shapely.points(rng.uniform([3.13, -7.09], [15.03, 2.71], (250, 2)))
        for radius in (0.1, 0.5, 1.1):
            accepted = surface.fits_soil(points, radius)
            assert np.all(shapely.contains(exact, points[accepted]))
            assert np.all(shapely.distance(points[accepted], exact.boundary) >= radius - 1e-9)


def test_every_point_in_exported_zone_respects_the_distance_rule() -> None:
    pipe = LineString([(0, -10), (0, 20)])
    rule = DistanceRule(
        "test-distance",
        ObjectClass.UTILITY_WATER,
        PlantingType.TREE,
        2.2,
        MeasureTo.AXIS,
        Severity.FORBID,
        Citation("test", "test", "Synthetic distance", CitationStatus.UNVERIFIED),
    )
    index = ConstraintIndex(
        [
            feature(ObjectClass.WORK_BOUNDARY, box(-0.2, 0, 10, 10)),
            feature(ObjectClass.UTILITY_WATER, pipe),
        ],
        [rule],
        require_utility_data=True,
    )
    zones = build_zones(index, 1.0)
    assert zones
    for zone in zones:
        assert zone.geometry.distance(pipe) >= 2.2 - 1e-3
        assert box(-0.2, 0, 10, 10).covers(zone.geometry)
