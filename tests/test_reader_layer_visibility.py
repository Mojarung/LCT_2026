"""Layer visibility changes material text, while physical geometry and diameters survive."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

import ezdxf
import pytest

from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.entities import Layer

    from green.domain.objects import Scene


def set_state(layer: Layer, state: str) -> None:
    if state == "off":
        layer.off()
    if state == "frozen":
        layer.freeze()


def read(doc: Drawing, tmp_path: Path) -> Scene:
    doc.units = 6
    p = tmp_path / "case.dxf"
    doc.saveas(p)
    h = sha256(p.read_bytes()).hexdigest()
    scene = EzdxfSceneReader().read(p)
    assert sha256(p.read_bytes()).hexdigest() == h
    assert sum(scene.read_diagnostics.outcomes.values()) == sum(
        scene.read_diagnostics.visited_by_type.values()
    )
    return scene


@pytest.mark.parametrize("state", ["off", "frozen"])
@pytest.mark.parametrize("kind", ["text", "mtext", "attrib"])
def test_direct_hidden_layer_text_excluded_diameter_kept_geometry_kept(
    state: str, kind: str, tmp_path: Path
) -> None:
    d = ezdxf.new("R2018")
    layer = d.layers.new("Водопровод")
    set_state(layer, state)
    m = d.modelspace()
    m.add_line((0, 0), (20, 0), dxfattribs={"layer": layer.dxf.name})
    if kind == "attrib":
        b = d.blocks.new("DIMTXT_ATTR")
        ins = m.add_blockref(b.name, (0, 0))
        for i, text in enumerate(["А", "d=400ст."]):
            ins.add_attrib(f"F{i}", text, (10, i), dxfattribs={"layer": "Водопровод"})
    else:
        for i, text in enumerate(["А", "d=400ст."]):
            add = m.add_text if kind == "text" else m.add_mtext
            add(text, dxfattribs={"insert": (10, i), "layer": "вОДОПРОВОД"})
    scene = read(d, tmp_path)
    assert not scene.labels
    assert [label.text for label in scene.hidden_diameter_labels] == ["d=400ст."]
    assert len(scene.features) == 1
    assert scene.features[0].geometry.length == 20


@pytest.mark.parametrize("state", ["off", "frozen"])
@pytest.mark.parametrize("child_layer", ["0", "Visible"])
@pytest.mark.parametrize("depth", [1, 3])
def test_hidden_parent_insert_suppresses_nested_text_and_attrib_but_not_geometry_or_siblings(
    state: str, child_layer: str, depth: int, tmp_path: Path
) -> None:
    d = ezdxf.new("R2018")
    hidden = d.layers.new("Hidden")
    set_state(hidden, state)
    d.layers.new("Visible")
    leaf = d.blocks.new("DIMTXT_LEAF")
    leaf.add_text("А", dxfattribs={"layer": child_layer, "insert": (10, 1)})
    leaf.add_line((0, 0), (20, 0), dxfattribs={"layer": child_layer})
    previous = leaf
    for i in range(depth):
        b = d.blocks.new(f"DIMTXT_NEST_{i}")
        ins = b.add_blockref(previous.name, (0, 0), dxfattribs={"layer": "0"})
        ins.add_attrib("DIAM", "d=400ст.", (10, 1), dxfattribs={"layer": child_layer})
        previous = b
    d.modelspace().add_blockref(previous.name, (0, 0), dxfattribs={"layer": "Hidden"})
    d.modelspace().add_text("ГАЗОН", dxfattribs={"layer": "Visible", "insert": (30, 0)})
    scene = read(d, tmp_path)
    assert [label.text for label in scene.labels] == ["ГАЗОН"]
    assert len(scene.hidden_diameter_labels) == depth
    assert len(scene.features) == 1
    assert scene.features[0].geometry.length == 20


@pytest.mark.parametrize("state", ["on", "off", "frozen"])
def test_unrelated_layer_and_print_flag_do_not_hide_visible_text(
    state: str, tmp_path: Path
) -> None:
    d = ezdxf.new("R2018")
    set_state(d.layers.new("Unused"), state)
    d.layers.new("Visible", dxfattribs={"plot": 0})
    d.modelspace().add_text("А", dxfattribs={"layer": "Visible", "insert": (10, 10)})
    assert [label.text for label in read(d, tmp_path).labels] == ["А"]
