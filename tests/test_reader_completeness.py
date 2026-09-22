"""Block geometry must not disappear just because the block is small or nested."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf import xref
from test_pipeline_synthetic import ROOT, _street

from green.application.errors import InputError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path


def test_missing_xref_nested_in_a_small_wrapper_is_reported(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    xref.define(doc, block_name="missing_network", filename="network.dxf")
    wrapper = doc.blocks.new("wrapper")
    wrapper.add_blockref("missing_network", (0, 0))
    doc.modelspace().add_blockref("wrapper", (100, 200))
    source = tmp_path / "nested.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source, unit="m")
    assert any("missing_network" in warning for warning in scene.warnings)


def test_short_pipe_inside_a_block_keeps_its_transformed_axis(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.layers.add("Водопровод")
    block = doc.blocks.new("short_pipe")
    block.add_line((0, 0), (2, 0))
    doc.modelspace().add_blockref(
        "short_pipe",
        (100, 200),
        dxfattribs={
            "layer": "Водопровод",
            "rotation": 90,
            "xscale": 2,
            "yscale": 2,
        },
    )
    source = tmp_path / "pipe.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source, unit="m")
    assert len(scene.features) == 1
    assert scene.features[0].geometry.geom_type == "LineString"
    assert list(scene.features[0].geometry.coords) == pytest.approx([(100, 200), (100, 204)])
    assert scene.features[0].layer == "Водопровод"


def test_minsert_retains_all_instances(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("msdElementTypeLine_test")
    block.add_line((0, 0), (2, 0))
    doc.modelspace().add_blockref(
        "msdElementTypeLine_test",
        (100, 200),
        dxfattribs={
            "row_count": 2,
            "column_count": 3,
            "row_spacing": 20,
            "column_spacing": 10,
        },
    )
    source = tmp_path / "array.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source, unit="m")
    assert len(scene.features) == 6
    assert {tuple(f.geometry.coords[0]) for f in scene.features} == {
        (x, y) for x in (100, 110, 120) for y in (200, 220)
    }
    assert len({str(f.ref) for f in scene.features}) == 6


def test_closed_curved_boundary_keeps_its_area(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.modelspace().add_lwpolyline([(0, 0, 1), (10, 0, 1)], format="xyb", close=True)
    source = tmp_path / "curved.dxf"
    doc.saveas(source)
    scene = EzdxfSceneReader().read(source, unit="m")
    assert scene.features[0].geometry.geom_type == "Polygon"
    assert scene.features[0].geometry.area == pytest.approx(78.54, rel=0.03)


@pytest.mark.parametrize("profile", ["strict", "no_utilities"])
def test_unresolved_xref_cannot_produce_an_approved_plan(tmp_path: Path, profile: str) -> None:
    source = tmp_path / "street.dxf"
    _street(source)
    doc = ezdxf.readfile(source)
    xref.attach(doc, block_name="unknown_network", filename="missing.dxf")
    doc.saveas(source)
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=tmp_path / "runs"))
    params = container.profiles.load(profile, {})
    with pytest.raises(InputError, match="unknown_network"):
        container.use_case.execute(PlanRequest("xref", source, tmp_path / "out", profile, params))
    assert not (tmp_path / "out/result.dxf").exists()


@pytest.mark.parametrize("name", ["arbitrary-01", "Слой_77", "msdElementTypeCustom"])
@pytest.mark.parametrize("angle", [0, 37, 90, 183])
@pytest.mark.parametrize("scale", [0.5, 2.0, -1.0])
def test_axis_survives_renaming_rotation_scale_and_translation(
    tmp_path: Path,
    name: str,
    angle: int,
    scale: float,
) -> None:
    doc = ezdxf.new("R2018")
    doc.layers.add(name)
    block = doc.blocks.new(name)
    block.add_line((0, 0), (2, 0))
    doc.modelspace().add_blockref(
        name,
        (1_000_000, -500_000),
        dxfattribs={
            "layer": name,
            "rotation": angle,
            "xscale": scale,
            "yscale": scale,
        },
    )
    path = tmp_path / "transformed.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    assert len(scene.features) == 1
    feature = scene.features[0]
    assert feature.geometry.geom_type == "LineString"
    radians = math.radians(angle)
    expected = [
        (1_000_000, -500_000),
        (
            1_000_000 + 2 * scale * math.cos(radians),
            -500_000 + 2 * scale * math.sin(radians),
        ),
    ]
    for actual, target in zip(feature.geometry.coords, expected, strict=True):
        assert actual == pytest.approx(target, abs=1e-8)
    assert feature.layer == name
    assert not scene.read_diagnostics.block_failures


def test_text_only_scene_still_converts_label_coordinates_to_metres(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.modelspace().add_text("ГАЗОН").set_placement((10000, 20000))
    path = tmp_path / "labels.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="mm")
    assert not scene.features
    assert (scene.labels[0].x, scene.labels[0].y) == (10, 20)


def test_recursive_block_is_a_reported_gap(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("cycle")
    block.add_blockref("cycle", (1, 0))
    doc.modelspace().add_blockref("cycle", (0, 0))
    path = tmp_path / "cycle.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    assert "INSERT:too-deep" in scene.read_diagnostics.block_failures
