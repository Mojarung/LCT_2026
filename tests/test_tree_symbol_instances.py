"""A CAD tree symbol has one trunk, even when its block has many primitives."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
import orjson
import pytest

from green.application.classification import LayerMap, classification_report, classify_scene
from green.application.params import PlanParams
from green.domain.objects import ObjectClass
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource
from green.infrastructure.reports.semantic_review import save_review_geometry

if TYPE_CHECKING:
    from ezdxf.document import Drawing

    from green.domain.objects import Scene


def _tree_block(doc: Drawing) -> None:
    sign = doc.blocks.new("TREE_SIGN")
    sign.add_circle((0, 0), 1.5)
    sign.add_circle((0, 0), 0.25)
    sign.add_line((-0.5, 0), (0.5, 0))
    sign.add_line((0, -0.5), (0, 0.5))


def _classified(path: Path) -> tuple[Scene, Scene]:
    scene = EzdxfSceneReader().read(path, unit="m")
    params = PlanParams(block_classes={"TREE_SIGN": "existing_tree"})
    return scene, classify_scene(scene, LayerMap((), "test"), params)[0]


def test_each_insert_is_one_tree_with_traced_parts(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    _tree_block(doc)
    msp = doc.modelspace()
    first = msp.add_blockref("TREE_SIGN", (10, 20))
    second = msp.add_blockref("TREE_SIGN", (40, 50), dxfattribs={"rotation": 37})
    path = tmp_path / "two_symbols.dxf"
    doc.saveas(path)

    raw, classified = _classified(path)

    assert len(raw.features) == 8
    trees = [f for f in classified.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert len(trees) == 2
    assert {next(iter(f.geometry.coords)) for f in trees} == {(10, 20), (40, 50)}
    assert {f.ref.handle for f in trees} == {first.dxf.handle, second.dxf.handle}
    assert all(len(f.symbol_parts) == 4 for f in trees)
    assert len({str(ref) for tree in trees for ref in tree.symbol_parts}) == 8
    review = save_review_geometry(
        tmp_path, classification_report(classified, LayerMap((), "test")), classified, None
    )
    exported = orjson.loads(review["semantic-review.geojson"].read_bytes())
    assert {item["id"] for item in exported["features"]} == {str(tree.ref) for tree in trees}
    assert {
        ref for item in exported["features"] for ref in item["properties"]["symbol_parts"]
    } == {str(ref) for tree in trees for ref in tree.symbol_parts}


@pytest.mark.parametrize("nested", [False, True])
def test_minsert_and_nested_blocks_keep_distinct_tree_instances(
    tmp_path: Path, *, nested: bool
) -> None:
    doc = ezdxf.new("R2018")
    _tree_block(doc)
    layout = doc.modelspace()
    if nested:
        wrapper = doc.blocks.new("WRAPPER")
        layout = wrapper
    layout.add_blockref(
        "TREE_SIGN",
        (10, 20),
        dxfattribs={"row_count": 2, "column_count": 2, "row_spacing": 10, "column_spacing": 20},
    )
    if nested:
        doc.modelspace().add_blockref("WRAPPER", (100, 200))
    path = tmp_path / "array.dxf"
    doc.saveas(path)

    raw, classified = _classified(path)

    assert len(raw.features) == 16
    trees = [f for f in classified.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert len(trees) == 4
    offset = (100, 200) if nested else (0, 0)
    assert {next(iter(f.geometry.coords)) for f in trees} == {
        (10 + x + offset[0], 20 + y + offset[1]) for x in (0, 20) for y in (0, 10)
    }
    assert all(len(f.symbol_parts) == 4 for f in trees)
    assert len({str(f.ref) for f in trees}) == 4


def test_unblocked_tree_circle_stays_its_own_tree(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.modelspace().add_circle((10, 20), 0.25, dxfattribs={"layer": "Дендра_сохранить"})
    path = tmp_path / "unblocked.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    params = PlanParams(layer_classes={"Дендра_сохранить": "existing_tree"})

    classified, _ = classify_scene(scene, LayerMap((), "test"), params)

    assert len(classified.features) == 1
    assert classified.features[0].geometry.geom_type == "Point"
    assert classified.features[0].symbol_parts == ()


def test_repeated_wrapper_keeps_each_inner_symbol_and_source_unique(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    _tree_block(doc)
    wrapper = doc.blocks.new("WRAPPER")
    wrapper.add_blockref("TREE_SIGN", (5, 0))
    wrapper.add_blockref("TREE_SIGN", (25, 0))
    doc.modelspace().add_blockref("WRAPPER", (0, 0))
    doc.modelspace().add_blockref("WRAPPER", (100, 0))
    path = tmp_path / "wrappers.dxf"
    doc.saveas(path)

    raw, classified = _classified(path)

    assert len(raw.features) == 16
    trees = [f for f in classified.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert {next(iter(f.geometry.coords)) for f in trees} == {
        (5, 0),
        (25, 0),
        (105, 0),
        (125, 0),
    }
    assert len({str(f.ref) for f in trees}) == 4
    assert len({str(ref) for tree in trees for ref in tree.symbol_parts}) == 16


@pytest.mark.parametrize(
    ("rotation", "xscale", "expected"),
    [(90, 2, (100, 210)), (0, -2, (90, 200))],
)
def test_nested_symbol_anchor_follows_outer_transform(
    tmp_path: Path, rotation: float, xscale: float, expected: tuple[float, float]
) -> None:
    doc = ezdxf.new("R2018")
    _tree_block(doc)
    wrapper = doc.blocks.new("WRAPPER")
    wrapper.add_blockref("TREE_SIGN", (5, 0))
    doc.modelspace().add_blockref(
        "WRAPPER", (100, 200), dxfattribs={"rotation": rotation, "xscale": xscale}
    )
    path = tmp_path / "transformed_wrapper.dxf"
    doc.saveas(path)

    _, classified = _classified(path)

    trees = [
        feature
        for feature in classified.features
        if feature.object_class is ObjectClass.EXISTING_TREE
    ]
    assert len(trees) == 1
    assert next(iter(trees[0].geometry.coords)) == pytest.approx(expected)


def test_known_dendrology_layer_treats_anonymous_block_as_one_symbol(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    sign = doc.blocks.new("*U57")
    sign.add_circle((0, 0), 0.7)
    sign.add_circle((0, 0), 0.8)
    sign.add_line((-0.5, 0), (0.5, 0))
    doc.layers.add("!!!_1. Дендра_сохранить")
    msp = doc.modelspace()
    for x in (10, 30):
        msp.add_blockref("*U57", (x, 20), dxfattribs={"layer": "!!!_1. Дендра_сохранить"})
    path = tmp_path / "dendrology.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path, unit="m")
    rules = YamlLayerMapSource(
        Path(__file__).resolve().parents[1] / "config/layer_map.yaml"
    ).load()
    classified, _ = classify_scene(scene, rules)

    assert len(scene.features) == 6
    trees = [f for f in classified.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert len(trees) == 2
    assert {next(iter(f.geometry.coords)) for f in trees} == {(10, 20), (30, 20)}
    assert all(len(f.symbol_parts) == 3 for f in trees)


def test_dendrology_symbol_with_nested_decoration_is_one_tree(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.layers.add("!!!_1. Дендра_сохранить")
    decoration = doc.blocks.new("DECORATION")
    decoration.add_circle((0, 0), 0.5)
    decoration.add_line((-0.5, 0), (0.5, 0))
    sign = doc.blocks.new("TREE_SIGN")
    sign.add_blockref("DECORATION", (0, 0))
    sign.add_blockref("DECORATION", (0, 0), dxfattribs={"rotation": 90})
    for x in (10, 30):
        doc.modelspace().add_blockref(
            "TREE_SIGN", (x, 20), dxfattribs={"layer": "!!!_1. Дендра_сохранить"}
        )
    path = tmp_path / "dendrology_nested.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path, unit="m")
    rules = YamlLayerMapSource(
        Path(__file__).resolve().parents[1] / "config/layer_map.yaml"
    ).load()
    classified, _ = classify_scene(scene, rules)

    assert len(scene.features) == 8
    trees = [f for f in classified.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert len(trees) == 2
    assert {next(iter(f.geometry.coords)) for f in trees} == {(10, 20), (30, 20)}
    assert all(len(f.symbol_parts) == 4 for f in trees)


def test_tree_assignment_on_outer_insert_reaches_nested_decorative_block(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    decor = doc.blocks.new("DECOR_ONLY")
    decor.add_circle((0, 0), 0.8)
    decor.add_line((-0.5, 0), (0.5, 0))
    sign = doc.blocks.new("TREE_SIGN")
    sign.add_blockref("DECOR_ONLY", (0, 0))
    for x in (10, 30):
        doc.modelspace().add_blockref("TREE_SIGN", (x, 20))
    path = tmp_path / "nested_decor.dxf"
    doc.saveas(path)

    raw, classified = _classified(path)

    assert len(raw.features) == 4
    trees = [f for f in classified.features if f.object_class is ObjectClass.EXISTING_TREE]
    assert len(trees) == 2
    assert {next(iter(f.geometry.coords)) for f in trees} == {(10, 20), (30, 20)}
    assert all(len(f.symbol_parts) == 2 for f in trees)


def test_feature_override_can_assign_whole_insert_as_one_tree(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    _tree_block(doc)
    doc.modelspace().add_blockref("TREE_SIGN", (10, 20))
    path = tmp_path / "feature_override.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    insert_ref = scene.features[0].insert_chain[0].ref
    params = PlanParams(feature_classes={str(insert_ref): "existing_tree"})

    classified, _ = classify_scene(scene, LayerMap((), "test"), params)
    report = classification_report(classified, LayerMap((), "test"), params)

    assert len(classified.features) == 1
    assert classified.features[0].ref == insert_ref
    assert len(classified.features[0].symbol_parts) == 4
    assert report.ready


def test_feature_override_on_a_symbol_part_is_recorded_as_used(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    _tree_block(doc)
    doc.modelspace().add_blockref("TREE_SIGN", (10, 20))
    path = tmp_path / "part_override.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    part_ref = scene.features[0].ref
    params = PlanParams(
        block_classes={"TREE_SIGN": "existing_tree"},
        feature_classes={str(part_ref): "existing_tree"},
    )

    classified, _ = classify_scene(scene, LayerMap((), "test"), params)
    report = classification_report(classified, LayerMap((), "test"), params)

    assert len(classified.features) == 1
    assert part_ref in classified.features[0].symbol_parts
    assert report.ready


def test_insert_override_can_reject_a_false_tree_sign(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    _tree_block(doc)
    doc.layers.add("!!!_1. Дендра_сохранить")
    doc.modelspace().add_blockref(
        "TREE_SIGN", (10, 20), dxfattribs={"layer": "!!!_1. Дендра_сохранить"}
    )
    path = tmp_path / "reject_false_sign.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    insert_ref = scene.features[0].insert_chain[0].ref
    params = PlanParams(feature_classes={str(insert_ref): "ignore"})
    rules = YamlLayerMapSource(
        Path(__file__).resolve().parents[1] / "config/layer_map.yaml"
    ).load()

    classified, _ = classify_scene(scene, rules, params)
    report = classification_report(classified, rules, params)

    assert len(classified.features) == 4
    assert all(feature.object_class is ObjectClass.IGNORE for feature in classified.features)
    assert report.ready


def test_layer_override_on_collapsed_symbol_part_remains_visible(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    sign = doc.blocks.new("TREE_SIGN")
    sign.add_circle((0, 0), 0.8, dxfattribs={"layer": "CROWN"})
    sign.add_line((-0.5, 0), (0.5, 0), dxfattribs={"layer": "TRUNK"})
    doc.modelspace().add_blockref("TREE_SIGN", (10, 20))
    path = tmp_path / "mixed_layers.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    params = PlanParams(
        block_classes={"TREE_SIGN": "existing_tree"},
        layer_classes={"TRUNK": "existing_tree"},
    )

    classified, _ = classify_scene(scene, LayerMap((), "test"), params)
    report = classification_report(classified, LayerMap((), "test"), params)

    assert len(classified.features) == 1
    assert report.ready
