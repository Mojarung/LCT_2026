"""Analytic envelopes bound CAD curves without inventing material."""

import math

import ezdxf
import numpy as np
import pytest
import shapely
from ezdxf.math import Vec3
from shapely.geometry import box

from green.infrastructure.cad.hatch_footprint import bounded_hatch_footprint


@pytest.mark.parametrize("kind", ["arc", "ellipse", "bulge"])
def test_analytic_envelope_contains_native_curve(kind: str) -> None:
    doc = ezdxf.new("R2018")
    hatch = doc.modelspace().add_hatch(dxfattribs={"extrusion": (0, 1, 1), "elevation": (0, 0, 7)})
    center = (100.0, 50.0)
    if kind == "bulge":
        hatch.paths.add_polyline_path([(90, 50, 1), (110, 50, 0)], is_closed=False)
        major, minor = (10.0, 0.0), (0.0, 10.0)
    else:
        path = hatch.paths.add_edge_path()
        if kind == "arc":
            path.add_arc(center, 10, 12, 289)
            major, minor = (10.0, 0.0), (0.0, 10.0)
        else:
            path.add_ellipse(center, (8, 6), 0.4, 12, 289)
            major, minor = (8.0, 6.0), (-2.4, 3.2)
    envelope = bounded_hatch_footprint(hatch, 0.001)
    assert envelope is not None
    ocs = hatch.ocs()
    samples = []
    for angle in np.linspace(0, math.tau, 1001):
        x = center[0] + major[0] * math.cos(angle) + minor[0] * math.sin(angle)
        y = center[1] + major[1] * math.cos(angle) + minor[1] * math.sin(angle)
        wcs = ocs.to_wcs(Vec3(x, y, 7))
        samples.append((wcs.x, wcs.y))
    assert np.all(shapely.covers(envelope, shapely.points(samples)))


def test_spline_hatch_cannot_use_unproved_envelope() -> None:
    doc = ezdxf.new()
    hatch = doc.modelspace().add_hatch()
    hatch.paths.add_edge_path().add_spline(fit_points=[(0, 0), (5, 10), (10, 0)])
    assert bounded_hatch_footprint(hatch, 0.1) is None


def test_open_polyline_last_bulge_is_still_enclosed() -> None:
    doc = ezdxf.new()
    hatch = doc.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (10, 0, 1)], is_closed=False)
    envelope = bounded_hatch_footprint(hatch, 0.01)
    assert envelope is not None
    assert envelope.covers(box(0, -5, 10, 5))
