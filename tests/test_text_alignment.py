"""DXF group 11 locates justified text; group 10 may be stale and far away."""

from __future__ import annotations

from pathlib import Path

import ezdxf
import numpy as np
import pytest
from shapely.geometry import Point, box

from green.application.classification import classify_scene
from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.application.surfaces import Material, build_surface_map
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource


@pytest.mark.parametrize(
    ("horizontal", "vertical"), [(1, 0), (2, 0), (4, 0), (0, 1), (1, 2), (2, 3)]
)
@pytest.mark.parametrize("normal", [(0, 0, 1), (0, 0, -1)])
@pytest.mark.parametrize(("unit", "factor"), [(6, 1.0), (4, 0.001)])
def test_justified_text_uses_alignment_point_in_world_metres(  # noqa: PLR0913, PLR0917 - alignment/frame/unit cross-product
    tmp_path: Path,
    horizontal: int,
    vertical: int,
    normal: tuple[int, int, int],
    unit: int,
    factor: float,
) -> None:
    doc = ezdxf.new("R2018")
    doc.units = unit
    doc.modelspace().add_text(
        "ГАЗОН",
        dxfattribs={
            "insert": (2, 3),
            "align_point": (100, 200),
            "halign": horizontal,
            "valign": vertical,
            "extrusion": normal,
        },
    )
    path = tmp_path / "aligned.dxf"
    doc.saveas(path)
    label = EzdxfSceneReader().read(path).labels[0]
    assert (label.x, label.y) == pytest.approx((normal[2] * 100 * factor, 200 * factor))


def test_material_assignment_follows_real_alignment_anchor(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    doc.layers.new("Бортовой камень")
    for left in (0, 20):
        doc.modelspace().add_lwpolyline(
            [(left, 0), (left + 20, 0), (left + 20, 20), (left, 20)],
            close=True,
            dxfattribs={"layer": "Бортовой камень"},
        )
    doc.modelspace().add_text(
        "ГАЗОН", dxfattribs={"insert": (10, 10), "align_point": (30, 10), "halign": 1}
    )
    path = tmp_path / "regions.dxf"
    doc.saveas(path)
    rules = YamlLayerMapSource(Path(__file__).resolve().parents[1] / "config/layer_map.yaml").load()
    scene, _ = classify_scene(EzdxfSceneReader().read(path), rules)
    surface = build_surface_map(scene.features, scene.labels, box(0, 0, 40, 20), 0.5)
    assert surface is not None
    assert list(surface.material(np.array([Point(10, 10), Point(30, 10)], dtype=object))) == [
        Material.UNKNOWN,
        Material.SOIL,
    ]


def test_justified_text_inside_rotated_block(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    block = doc.blocks.new("Unknown")
    block.add_text("ГАЗОН", dxfattribs={"insert": (0, 0), "align_point": (3, 4), "halign": 2})
    doc.modelspace().add_blockref("Unknown", (100, 200), dxfattribs={"rotation": 90})
    path = tmp_path / "nested.dxf"
    doc.saveas(path)
    label = EzdxfSceneReader().read(path).labels[0]
    assert (label.x, label.y) == pytest.approx((96, 203))


def test_justified_attribute_uses_its_instance_alignment(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    doc.blocks.new("Unknown")
    instance = doc.modelspace().add_blockref("Unknown", (100, 200))
    instance.add_attrib(
        "MATERIAL", "ГАЗОН", (0, 0), dxfattribs={"align_point": (130, 240), "halign": 1}
    )
    path = tmp_path / "attribute.dxf"
    doc.saveas(path)
    label = EzdxfSceneReader().read(path).labels[0]
    assert (label.x, label.y) == pytest.approx((130, 240))


@pytest.mark.parametrize("horizontal", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("nested", [False, True])
def test_missing_required_alignment_is_not_replaced_with_insert(
    tmp_path: Path, horizontal: int, *, nested: bool
) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    target = doc.blocks.new("Unknown") if nested else doc.modelspace()
    target.add_text("ГАЗОН", dxfattribs={"insert": (10, 10), "halign": horizontal})
    if nested:
        doc.modelspace().add_blockref("Unknown", (100, 200), dxfattribs={"rotation": 47})
    path = tmp_path / "missing-alignment.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path)
    assert not scene.labels
    assert scene.read_diagnostics.geometry_gaps[0].reason == "text-alignment-point-missing"
    with pytest.raises(InputError, match="text-alignment-point-missing"):
        require_complete_geometry(scene)


@pytest.mark.parametrize("kind", ["TEXT", "MTEXT"])
def test_nonfinite_label_cannot_enter_surface_inference(tmp_path: Path, kind: str) -> None:
    doc = ezdxf.new("R2018")
    doc.units = 6
    factory = doc.modelspace().add_text if kind == "TEXT" else doc.modelspace().add_mtext
    factory("ГАЗОН", dxfattribs={"insert": (float("nan"), 10)})
    path = tmp_path / "nonfinite-label.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path)
    assert not scene.labels
    assert scene.read_diagnostics.geometry_gaps[0].reason == "non-finite-text-coordinates"
    with pytest.raises(InputError, match="non-finite-text-coordinates"):
        require_complete_geometry(scene)
