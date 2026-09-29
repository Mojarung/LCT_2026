"""Input overlap warnings: no street names, invented crowns, or geometry repair."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from shapely.geometry.base import BaseGeometry

import ezdxf
import pytest
from ezdxf import xref
from shapely.affinity import affine_transform
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    box,
    mapping,
)

from green.application.basemap import build_basemap
from green.application.semantic_names import local_name
from green.application.source_conflicts import enrich_saved_basemap, find_source_conflicts
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.cad.merge import EzdxfDrawingMerger
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.reports.artifacts import _basemap


def feature(
    key: str,
    kind: ObjectClass,
    geometry: BaseGeometry,
    *,
    source_entity_type: str | None = None,
    geometry_error_m: float | None = 0,
) -> Feature:
    return Feature(
        SourceRef("file1234", "xref1234", key),
        "arbitrary-layer",
        geometry,
        object_class=kind,
        source_entity_type=source_entity_type,
        geometry_error_m=geometry_error_m,
    )


def tree(
    key: str = "tree",
    x: float = 5,
    y: float = 5,
    *,
    source_entity_type: str | None = None,
    geometry_error_m: float | None = 0,
) -> Feature:
    return feature(
        key,
        ObjectClass.EXISTING_TREE,
        Point(x, y),
        source_entity_type=source_entity_type,
        geometry_error_m=geometry_error_m,
    )


@pytest.mark.parametrize("kind", [ObjectClass.SIDEWALK, ObjectClass.ROAD, ObjectClass.BUILDING])
def test_trunk_inside_explicit_area_is_advisory(kind: ObjectClass) -> None:
    area = feature("area", kind, box(0, 0, 10, 10))
    report = find_source_conflicts([tree(), area])
    assert report.checked_trees == 1
    assert len(report.items) == 1
    assert report.items[0].targets[0].object_class == str(kind)
    assert report.items[0].targets[0].depth_m == 5
    assert area.geometry.equals(box(0, 0, 10, 10))


def test_holes_and_disjoint_islands_are_preserved() -> None:
    polygon = Polygon(
        [(0, 0), (10, 0), (10, 10), (0, 10)], holes=[[(3, 3), (7, 3), (7, 7), (3, 7)]]
    )
    area = feature("area", ObjectClass.SIDEWALK, MultiPolygon([polygon, box(20, 20, 30, 30)]))
    report = find_source_conflicts(
        [tree(), tree("inside", 2, 2), tree("island", 25, 25), tree("outside", 15, 15), area]
    )
    assert [(x.x, x.y) for x in report.items] == [(2, 2), (25, 25)]


@pytest.mark.parametrize("x", [0, -0.1, 0.01, 0.05, 10])
def test_boundary_touch_and_rounding_are_not_definite_overlaps(x: float) -> None:
    assert not find_source_conflicts(
        [tree(x=x), feature("a", ObjectClass.ROAD, box(0, 0, 10, 10))]
    ).items


def test_geometry_error_and_uncertain_footprint_are_respected() -> None:
    area = feature("a", ObjectClass.SIDEWALK, box(0, 0, 10, 10), geometry_error_m=0.3)
    assert not find_source_conflicts([tree(x=0.2), area]).items
    assert find_source_conflicts([tree(x=0.4), area]).items
    uncertain = replace(area, uncertainty_footprint=box(0, 0, 6, 10))
    assert not find_source_conflicts([tree(), uncertain]).items


def test_duplicates_of_trunk_and_targets_do_not_multiply_locations() -> None:
    a = feature("a", ObjectClass.SIDEWALK, box(0, 0, 10, 10))
    t = tree()
    duplicate = replace(t, ref=SourceRef("another", "ref-copy", "tree"))
    report = find_source_conflicts(
        [t, t, duplicate, a, a, feature("b", ObjectClass.BUILDING, box(1, 1, 9, 9))]
    )
    assert report.checked_trees == 1
    assert len(report.items) == 1
    assert len(report.items[0].tree_refs) == 2
    assert len(report.items[0].targets) == 2
    assert report == find_source_conflicts(
        [duplicate, t, t, a, a, feature("b", ObjectClass.BUILDING, box(1, 1, 9, 9))]
    )


def test_only_known_trunk_points_and_polygon_interiors_are_checked() -> None:
    area = feature("a", ObjectClass.SIDEWALK, box(0, 0, 10, 10))
    ignored = [
        tree("strip", source_entity_type="TREE_STRIP"),
        feature("crown", ObjectClass.EXISTING_TREE, Point(5, 5).buffer(2)),
        feature("shrub", ObjectClass.EXISTING_SHRUB, Point(5, 5)),
        tree("unknown-error", geometry_error_m=None),
    ]
    assert not find_source_conflicts([area, *ignored]).items
    for kind in (ObjectClass.LAWN, ObjectClass.PAVEMENT_EDGE, ObjectClass.CONTOUR):
        assert not find_source_conflicts([tree(), feature("shape", kind, box(0, 0, 10, 10))]).items
    assert not find_source_conflicts(
        [tree(), feature("open", ObjectClass.BUILDING, LineString([(0, 0), (10, 0), (10, 10)]))]
    ).items


def test_multiple_known_trunks_are_separate_but_strip_is_not() -> None:
    points = feature("points", ObjectClass.EXISTING_TREE, MultiPoint([(2, 2), (5, 5)]))
    area = feature("a", ObjectClass.BUILDING, box(0, 0, 10, 10))
    assert len(find_source_conflicts([points, area]).items) == 2
    assert not find_source_conflicts([replace(points, source_entity_type="TREE_STRIP"), area]).items


def test_invalid_or_empty_areas_do_not_become_invented_interiors() -> None:
    areas = [
        feature("invalid", ObjectClass.SIDEWALK, Polygon([(0, 0), (10, 10), (0, 10), (10, 0)])),
        feature("empty", ObjectClass.BUILDING, Polygon()),
        feature("collection", ObjectClass.ROAD, GeometryCollection([box(0, 0, 10, 10)])),
    ]
    report = find_source_conflicts([tree(), *areas])
    assert not report.items
    assert report.skipped_area_features == 3


@pytest.mark.parametrize(
    "transform", [[1, 0, 0, 1, 10000, -3000], [0, -1, 1, 0, -200, 400], [-2, 0, 0, 0.5, 800, 500]]
)
def test_translated_rotated_and_mirrored_geometry(transform: list[float]) -> None:
    features = [tree(), feature("a", ObjectClass.ROAD, box(0, 0, 10, 10))]
    moved = [replace(f, geometry=affine_transform(f.geometry, transform)) for f in features]
    assert len(find_source_conflicts(moved).items) == 1


@pytest.mark.parametrize(("unit", "scale"), [("m", 1), ("mm", 1000)])
@pytest.mark.parametrize("mirrored", [False, True])
def test_independent_dxf_block_and_units(
    tmp_path: Path, unit: str, scale: float, *, mirrored: bool
) -> None:
    doc = ezdxf.new("R2018")
    doc.layers.new("input-trees")
    doc.layers.new("input-paving")
    block = doc.blocks.new("unrelated-layout")
    block.add_point((5 * scale, 5 * scale), dxfattribs={"layer": "input-trees"})
    block.add_lwpolyline(
        [(0, 0), (10 * scale, 0), (10 * scale, 10 * scale), (0, 10 * scale)],
        close=True,
        dxfattribs={"layer": "input-paving"},
    )
    doc.modelspace().add_blockref(
        "unrelated-layout",
        (120 * scale, -80 * scale),
        dxfattribs={"rotation": 37, "xscale": -1 if mirrored else 1},
    )
    path = tmp_path / "independent.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit=unit)
    features = [
        replace(
            f,
            object_class=ObjectClass.EXISTING_TREE
            if f.layer == "input-trees"
            else ObjectClass.SIDEWALK,
        )
        for f in scene.features
    ]
    report = find_source_conflicts(features)
    assert len(report.items) == 1
    assert report.items[0].targets[0].depth_m == pytest.approx(5, abs=0.01)


def test_detection_precedes_map_simplification_and_budget() -> None:
    features = [tree(), feature("a", ObjectClass.SIDEWALK, box(0, 0, 10, 10))]
    basemap = build_basemap(features, tolerance_m=2, feature_budget=1)
    payload = _basemap(basemap)
    assert payload["source_conflicts"]["basis"] == "source"
    assert len(payload["source_conflicts"]["items"]) == 1
    assert enrich_saved_basemap(payload) is payload


def test_legacy_fallback_keeps_holes_and_discloses_reduced_geometry() -> None:
    area = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], holes=[[(4, 4), (6, 4), (6, 6), (4, 6)]])
    features = [tree(), tree("second", 2, 2), feature("a", ObjectClass.SIDEWALK, area)]
    payload = {
        "features": [
            {"properties": {"class": str(f.object_class)}, "geometry": mapping(f.geometry)}
            for f in features
        ]
    }
    before = json.dumps(payload)
    result = enrich_saved_basemap(payload)["source_conflicts"]
    assert result["basis"] == "saved_basemap"
    assert len(result["items"]) == 1
    assert result["items"][0]["x"] == 2
    assert json.dumps(payload) == before


def test_legacy_ambiguous_multipoints_are_not_trunks() -> None:
    payload = {
        "features": [
            {
                "properties": {"class": "existing_tree"},
                "geometry": mapping(MultiPoint([(3, 3), (5, 5)])),
            },
            {"properties": {"class": "sidewalk"}, "geometry": mapping(box(0, 0, 10, 10))},
        ]
    }
    assert not enrich_saved_basemap(payload)["source_conflicts"]["items"]


def test_independent_external_reference_package(tmp_path: Path) -> None:
    asset, host = tmp_path / "survey.dxf", tmp_path / "layout.dxf"
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    doc.layers.new("trunks")
    doc.layers.new("hard-area")
    doc.modelspace().add_point((5, 5), dxfattribs={"layer": "trunks"})
    doc.modelspace().add_lwpolyline(
        [(0, 0), (10, 0), (10, 10), (0, 10)], close=True, dxfattribs={"layer": "hard-area"}
    )
    doc.saveas(asset)
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    xref.attach(
        doc,
        block_name="unknown-survey",
        filename="survey.dxf",
        insert=(500, 700),
        scale=-2,
        rotation=37,
    )
    doc.saveas(host)
    target = tmp_path / "merged.dxf"
    EzdxfDrawingMerger().merge([host, asset], target)
    scene = EzdxfSceneReader().read(target)
    features = [
        replace(
            f,
            object_class=ObjectClass.EXISTING_TREE
            if local_name(f.layer) == "trunks"
            else ObjectClass.SIDEWALK,
        )
        for f in scene.features
    ]
    report = find_source_conflicts(features)
    assert len(report.items) == 1
    assert report.items[0].targets[0].depth_m == pytest.approx(10, abs=0.01)
