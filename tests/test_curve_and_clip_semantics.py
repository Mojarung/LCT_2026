"""Open arcs must not create land; clipping must not silently expose hidden areas."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.xclip import XClip

from green.application.input_quality import require_complete_geometry
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("sweep", [30, 90, 180, 270])
@pytest.mark.parametrize("extrusion", [(0, 0, 1), (0, 0, -1)])
def test_arc_remains_open_and_has_no_invented_area(
    tmp_path: Path, sweep: float, extrusion: tuple[int, int, int]
) -> None:
    doc = ezdxf.new("R2018")
    doc.layers.add("Леса и газоны")
    doc.modelspace().add_arc(
        (100, 200), 10, 0, sweep, dxfattribs={"layer": "Леса и газоны", "extrusion": extrusion}
    )
    path = tmp_path / "arc.dxf"
    doc.saveas(path)
    feature = EzdxfSceneReader().read(path, unit="m").features[0]
    assert feature.geometry.geom_type == "LineString"
    assert feature.geometry.area == 0
    assert not feature.geometry.is_ring
    assert feature.geometry.length == pytest.approx(10 * math.radians(sweep), rel=0.01)
    sign = extrusion[2]
    assert tuple(feature.geometry.coords[0]) == pytest.approx((110 * sign, 200))
    assert tuple(feature.geometry.coords[-1]) == pytest.approx(
        (
            (100 + 10 * math.cos(math.radians(sweep))) * sign,
            200 + 10 * math.sin(math.radians(sweep)),
        )
    )


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("nested", [False, True])
def test_enabled_xclip_crops_the_block_as_cad_shows_it(
    tmp_path: Path, *, enabled: bool, nested: bool
) -> None:
    """Обрезка XCLIP применяется: за рамкой нет ни грунта, ни объектов (раньше вставка с
    обрезкой была пробелом, пока точная обрезка не поддержана; 25.09.2026 поддержана).
    Вложенная вставка с обрезкой внутри повёрнутого блока режется своей рамкой тоже."""
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("lawn")
    block.add_lwpolyline([(0, 0), (100, 0), (100, 100), (0, 100)], close=True)
    space = doc.blocks.new("outer") if nested else doc.modelspace()
    insert = space.add_blockref("lawn", (10, 20))
    clip = XClip(insert)
    clip.set_block_clipping_path([(0, 0), (10, 10)])
    if not enabled:
        clip.disable_clipping()
    if nested:
        doc.modelspace().add_blockref("outer", (0, 0), dxfattribs={"rotation": 45})
    path = tmp_path / "clipped.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    require_complete_geometry(scene)
    assert len(scene.features) == 1
    assert scene.features[0].geometry.area == pytest.approx(100 if enabled else 10000)
    if enabled:
        # Центр рамки (5, 5) блока: вставка в (10, 20), у вложенной ещё поворот на 45 градусов.
        centre = scene.features[0].geometry.centroid
        half = math.sqrt(0.5)
        expected = ((15 - 25) * half, (15 + 25) * half) if nested else (15, 25)
        assert (centre.x, centre.y) == pytest.approx(expected)
