"""Sign 273, independently of street name, origin, CAD units and XREF placement."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf import xref
from shapely.geometry import Point, box
from test_pipeline_synthetic import ROOT
from tools.make_demo_fragment import write_fragment

from green.application.basemap import build_basemap
from green.application.classification import classify_scene
from green.application.shrub_strips import SHRUB_STRIP_SOURCE, recognise_shrub_strips
from green.application.stock import stock_of
from green.domain.objects import ClassificationEvidence, ObjectClass
from green.infrastructure.cad.merge import EzdxfDrawingMerger
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource
from green.infrastructure.reports.artifacts import _basemap

if TYPE_CHECKING:
    from pathlib import Path

    from green.application.params import PlanParams
    from green.domain.objects import Feature, Scene

RADII = [0.04] * 5 + [0.175, 0.25, 0.175] + [0.04] * 5 + [0.175, 0.25, 0.175] + [0.04] * 5


def drawing(
    path: Path,
    radii: list[float] = RADII,
    *,
    layer: str = "Полоса деревьев",
    unit: int = 6,
    multiple: float = 1,
) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = unit
    doc.layers.add(layer)
    for i, radius in enumerate(radii):
        doc.modelspace().add_circle(
            (i * 0.7 * multiple, 0), radius * multiple, dxfattribs={"layer": layer}
        )
        if radius == 0.04:
            doc.modelspace().add_line(
                ((i * 0.7 - 0.02) * multiple, 0),
                ((i * 0.7 + 0.02) * multiple, 0),
                dxfattribs={"layer": layer},
            )
    doc.saveas(path)


def classify(path: Path, params: PlanParams | None = None) -> Scene:
    source = EzdxfSceneReader().read(path)
    return classify_scene(
        source, YamlLayerMapSource(ROOT / "config/layer_map.yaml").load(), params
    )[0]


def hedges(scene: Scene) -> list[Feature]:
    return [f for f in scene.features if f.source_entity_type == SHRUB_STRIP_SOURCE]


@pytest.mark.parametrize(("unit", "multiple"), [(6, 1), (4, 1000)])
def test_standalone_symbol_is_one_band_not_trees_or_counted_shrubs(
    tmp_path: Path, unit: int, multiple: float
) -> None:
    path = tmp_path / "arbitrary-name.dxf"
    drawing(path, unit=unit, multiple=multiple)
    scene = classify(path)
    assert len(hedges(scene)) == 1
    hedge = hedges(scene)[0]
    assert hedge.object_class is ObjectClass.EXISTING_SHRUB
    assert hedge.geometry.length == pytest.approx(14)
    assert all(f.object_class is ObjectClass.IGNORE for f in scene.features if f is not hedge)
    stock = stock_of(scene.features, box(-10, -10, 30, 10), crown_m=8)
    assert stock.trees == stock.shrubs == 0
    assert len(stock.strips_xy) == 0
    assert stock.canopy is None
    payload = _basemap(build_basemap(scene.features))
    assert payload["features"][0]["properties"] == {
        "class": "existing_shrub",
        "vegetation_kind": "shrub_strip",
    }
    assert payload["features"][0]["geometry"]["type"] == "LineString"


@pytest.mark.parametrize(("angle", "scale"), [(0, 1), (37, 1), (117, 2), (90, -1)])
def test_xref_rotation_translation_reflection_and_scale(
    tmp_path: Path, angle: float, scale: float
) -> None:
    asset, host = tmp_path / "vegetation.dxf", tmp_path / "site.dxf"
    drawing(asset)
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    xref.attach(
        doc,
        block_name="unrelated-source",
        filename=asset.name,
        insert=(8000, -9000),
        rotation=angle,
        scale=scale,
    )
    doc.saveas(host)
    target = tmp_path / "merged.dxf"
    EzdxfDrawingMerger().merge([host, asset], target)
    found = hedges(classify(target))
    assert len(found) == 1
    assert found[0].geometry.length == pytest.approx(14 * abs(scale))
    assert found[0].geometry.distance(Point(8000, -9000)) < 1e-5


@pytest.mark.parametrize(
    "radii",
    [
        [0.25] * 21,
        [0.04] * 21,
        [0.04] * 5 + [0.175, 0.25, 0.175] + [0.04] * 5,
        [0.04, 0.25, 0.175] * 7,
        [0.175, 0.25, 0.175, 0.04, 0.175, 0.25, 0.175] + [0.04] * 4,
    ],
)
def test_ambiguous_or_incomplete_patterns_are_not_guessed_as_hedges(
    tmp_path: Path, radii: list[float]
) -> None:
    path = tmp_path / "ambiguous.dxf"
    drawing(path, radii)
    assert not hedges(classify(path))


def test_dense_individual_trees_on_another_layer_are_not_grouped(tmp_path: Path) -> None:
    path = tmp_path / "trees.dxf"
    drawing(path, [0.25] * 12, layer="Деревья существующие")
    scene = classify(path)
    assert not hedges(scene)
    assert sum(f.object_class is ObjectClass.EXISTING_TREE for f in scene.features) == 12
    assert not any(f.source_entity_type == "TREE_STRIP" for f in scene.features)


def test_explicit_assignment_takes_precedence(tmp_path: Path) -> None:
    path = tmp_path / "explicit.dxf"
    drawing(path)
    source = EzdxfSceneReader().read(path)
    # An explicit per-feature decision must never be consumed by geometric grouping.

    features = [
        replace(
            f,
            geometry=Point(f.circle_center_m),
            object_class=ObjectClass.EXISTING_TREE,
            classification=ClassificationEvidence("explicit_feature"),
        )
        for f in source.features
        if f.circle_center_m
    ]
    assert recognise_shrub_strips(features) == tuple(features)


def test_demo_export_preserves_circle_sizes_and_true_points(tmp_path: Path) -> None:

    path = tmp_path / "source.dxf"
    drawing(path)
    doc = ezdxf.readfile(path)
    doc.modelspace().add_point((30, 0))
    doc.saveas(path)
    source = EzdxfSceneReader().read(path)
    target = tmp_path / "fragment.dxf"
    write_fragment(list(source.features), [], (-1, -1, 40, 1), target, 1)
    reread = EzdxfSceneReader().read(target)
    assert sorted(f.circle_radius_m for f in reread.features if f.circle_radius_m) == sorted(RADII)
    assert len(hedges(classify(target))) == 1
    assert len(ezdxf.readfile(target).modelspace().query("POINT")) == 1


def test_real_holdout_drawings(tmp_path: Path) -> None:
    """Native circle coordinates and radii, independent streets, not generated motifs."""
    cases = json.loads(
        (ROOT / "tests/fixtures/topographic_shrub_strips.json").read_text(encoding="utf-8")
    )
    for case in cases:
        doc = ezdxf.new("R2018")
        doc.header["$INSUNITS"] = 6
        for circle in case["circles"]:
            layer = circle["layer"]
            if layer not in doc.layers:
                doc.layers.add(layer)
            doc.modelspace().add_circle(
                circle["center"], circle["radius"], dxfattribs={"layer": layer}
            )
        target = tmp_path / (case["source"] + ".dxf")
        doc.saveas(target)
        assert len(hedges(classify(target))) == case["expected_strips"], case["source"]


def test_hedge_can_turn_a_right_angle(tmp_path: Path) -> None:
    path = tmp_path / "corner.dxf"
    drawing(path)
    doc = ezdxf.readfile(path)
    for circle in doc.modelspace().query("CIRCLE"):
        x = circle.dxf.center.x
        if x > 7:
            circle.dxf.center = (7, x - 7, 0)
    # Remove only synthetic fill strokes, whose coordinates this fixture did not rotate.
    for line in list(doc.modelspace().query("LINE")):
        doc.modelspace().delete_entity(line)
    doc.saveas(path)
    assert len(hedges(classify(path))) == 1


@pytest.mark.parametrize("layer", ["Существующие кустарники", "Деревья существующие"])
def test_pattern_not_street_or_misleading_layer_name_decides_kind(
    tmp_path: Path, layer: str
) -> None:
    path = tmp_path / "renamed.dxf"
    drawing(path, layer=layer)
    assert len(hedges(classify(path))) == 1
