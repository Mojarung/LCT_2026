"""Unreadable HATCH is quarantined only within an analytic edge envelope."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import numpy as np
import pytest
import shapely
from ezdxf.math import Vec3
from shapely.geometry import Point, box
from test_pipeline_synthetic import ROOT

from green.application.classification import classify_scene
from green.application.input_quality import require_complete_geometry
from green.application.surfaces import Material, build_surface_map
from green.domain.objects import ObjectClass
from green.infrastructure.cad.hatch_footprint import bounded_hatch_footprint
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

if TYPE_CHECKING:
    from pathlib import Path


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


def test_disconnected_hatch_edges_are_bounded_but_not_filled(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "Газон"})
    path = hatch.paths.add_edge_path()
    path.add_line((0, 0), (10, 0))
    path.add_line((10, 10), (0, 10))
    source = tmp_path / "disconnected.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source, unit="m")
    require_complete_geometry(scene)
    assert scene.read_diagnostics.bounded_uncertainty_by_type == {"HATCH": 1}
    assert scene.features[0].uncertain_footprint
    assert scene.features[0].geometry.covers(box(0, 0, 10, 10))


def test_open_polyline_last_bulge_is_still_enclosed() -> None:
    doc = ezdxf.new()
    hatch = doc.modelspace().add_hatch()
    hatch.paths.add_polyline_path([(0, 0), (10, 0, 1)], is_closed=False)
    envelope = bounded_hatch_footprint(hatch, 0.01)
    assert envelope is not None
    assert envelope.covers(box(0, -5, 10, 5))


def test_distant_valid_paths_and_one_bad_path_do_not_mask_the_gap(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "Асфальт"})
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 10), (0, 10)], is_closed=True)
    hatch.paths.add_polyline_path([(100, 100), (110, 100), (110, 110), (100, 110)], is_closed=True)
    hatch.paths.add_polyline_path([(5, 5), (5.1, 5.1)], is_closed=True)
    source = tmp_path / "distant_paths.dxf"
    doc.saveas(source)

    scene = EzdxfSceneReader().read(source, unit="m")
    require_complete_geometry(scene)

    assert scene.read_diagnostics.bounded_uncertainty_by_type == {"HATCH": 1}
    uncertain = scene.features[0]
    assert uncertain.uncertain_footprint
    assert uncertain.geometry.covers(box(0, 0, 10, 10))
    assert uncertain.geometry.covers(box(100, 100, 110, 110))
    assert not uncertain.geometry.covers(Point(50, 50))
    assert uncertain.geometry.area < 300


def test_nested_bad_hatch_keeps_metre_scale_footprint(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 4  # millimetres
    block = doc.blocks.new("unfamiliar")
    hatch = block.add_hatch(dxfattribs={"layer": "0"})
    hatch.paths.add_polyline_path([(0, 0), (1000, 1000), (0, 1000), (1000, 0)])
    insert = doc.modelspace().add_blockref(
        block.name,
        (1_000_000, 500_000),
        dxfattribs={"rotation": 37, "xscale": 2, "yscale": 2, "layer": "Газон"},
    )
    source = tmp_path / "nested-mm.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source)
    require_complete_geometry(scene)
    assert len(scene.features) == 1
    feature = scene.features[0]
    assert feature.uncertain_footprint
    assert feature.geometry.area > 4
    assert feature.geometry.area < 12
    assert feature.layer == "Газон"
    assert feature.block == "unfamiliar"
    for x, y in [(0, 0), (1000, 1000), (0, 1000), (1000, 0)]:
        transformed = insert.matrix44().transform(Vec3(x, y, 0))
        assert feature.geometry.covers(Point(transformed.x / 1000, transformed.y / 1000))


def test_invalid_hatch_on_lawn_stays_unknown_after_classification(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    doc.layers.add("Газон")
    doc.modelspace().add_lwpolyline(
        [(0, 0), (50, 0), (50, 50), (0, 50)],
        close=True,
        dxfattribs={"layer": "Газон"},
    )
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "Газон"})
    hatch.paths.add_polyline_path([(10, 10), (20, 20), (10, 20), (20, 10)])
    path = tmp_path / "uncertain.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path)
    require_complete_geometry(scene)
    assert scene.read_diagnostics.bounded_uncertainty_by_type == {"HATCH": 1}
    uncertain = next(feature for feature in scene.features if feature.uncertain_footprint)
    assert uncertain.geometry.covers(box(10, 10, 20, 20))
    assert uncertain.geometry.area < 200
    rules = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    classified, _ = classify_scene(scene, rules)
    uncertain = next(feature for feature in classified.features if feature.uncertain_footprint)
    assert uncertain.object_class is ObjectClass.UNCERTAIN_AREA
    surface = build_surface_map(classified.features, [], box(0, 0, 50, 50), 0.5)
    assert surface is not None
    assert surface.material(np.array([Point(15, 15)], dtype=object))[0] == Material.UNKNOWN
    assert not surface.fits_soil(np.array([Point(15, 15)], dtype=object), 1)[0]
    assert surface.material(np.array([Point(40, 40)], dtype=object))[0] == Material.SOIL
