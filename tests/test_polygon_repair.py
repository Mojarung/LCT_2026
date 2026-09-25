"""Roundoff in CAD boundaries must not excuse a materially changed footprint."""

from __future__ import annotations

import pytest
from ezdxf.math import Vec3
from shapely.geometry import Polygon

from green.infrastructure.cad.hatch_geometry import HatchGeometryError, _checked_ring
from green.infrastructure.cad.polygon_repair import repair_roundoff_self_intersection
from green.infrastructure.cad.region_geometry import RegionGeometryError, _checked_polygon


def test_zero_width_overlap_keeps_its_boundary() -> None:
    # A real CAD contour: consecutive edges overlap by floating point roundoff.
    points = [
        (-3864.249169694, 6498.004551941),
        (-3864.118666241, 6497.174993521),
        (-3863.822311011, 6497.221615170),
        (-3863.952814465, 6498.051173589),
        (-3863.974500015, 6498.189019990),
        (-3865.261139848, 6498.138061340),
        (-3865.249267358, 6497.838296359),
        (-3864.229369566, 6497.878690425),
    ]
    original = Polygon(points)
    assert not original.is_valid

    repaired = repair_roundoff_self_intersection(original)
    assert repaired is not None
    assert repaired.is_valid
    assert repaired.boundary.hausdorff_distance(original.boundary) <= 1e-9
    assert abs(repaired.area - original.area) <= 1e-9
    assert _checked_polygon([Vec3(x, y, 0) for x, y in points]).equals(repaired)
    assert _checked_ring([Vec3(x, y, 0) for x, y in points]).equals(repaired)


def test_crossed_contour_remains_a_geometry_gap() -> None:
    points = [(0, 0), (2, 2), (0, 2), (2, 0)]
    polygon = Polygon(points)
    assert repair_roundoff_self_intersection(polygon) is None
    with pytest.raises(RegionGeometryError, match="acis-polygon-invalid"):
        _checked_polygon([Vec3(x, y, 0) for x, y in points])
    with pytest.raises(HatchGeometryError, match="hatch-invalid-ring"):
        _checked_ring([Vec3(x, y, 0) for x, y in points])
