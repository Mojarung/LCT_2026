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


@pytest.mark.parametrize("bulge", [1.421e-13, -1.421e-13, 1e-10])
def test_numerically_zero_bulge_reads_as_a_straight_segment(tmp_path: Path, bulge: float) -> None:
    """Олимпийская деревня: у борта выпуклость -1,421e-13 - в CAD это прямая. Дуга радиусом
    10^14 м расходилась концами на точности float, и улица останавливалась как нечитаемая."""
    doc = ezdxf.new("R2018")
    doc.layers.add("Борт")
    doc.modelspace().add_lwpolyline(
        [(-2577.858787, 514.084025, 0), (-2585.776897, 505.235108, bulge), (-2578.905, 498.179, 0)],
        format="xyb",
        dxfattribs={"layer": "Борт", "const_width": 0.15},
    )
    path = tmp_path / "bulge.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    require_complete_geometry(scene)
    line = scene.features[0].geometry
    assert line.geom_type == "LineString"
    assert tuple(line.coords[-1]) == pytest.approx((-2578.905, 498.179))
    assert line.length == pytest.approx(
        math.dist((-2577.858787, 514.084025), (-2585.776897, 505.235108))
        + math.dist((-2585.776897, 505.235108), (-2578.905, 498.179)),
        abs=1e-6,
    )


def test_numerically_zero_bulge_in_a_2d_polyline(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.layers.add("Борт")
    doc.modelspace().add_polyline2d(
        [(0, 0, 0), (10, 0, -1.421e-13), (10, 10, 0.5), (20, 10, 0)],
        format="xyb",
        dxfattribs={"layer": "Борт"},
    )
    path = tmp_path / "bulge2d.dxf"
    doc.saveas(path)
    scene = EzdxfSceneReader().read(path, unit="m")
    require_complete_geometry(scene)
    line = scene.features[0].geometry
    # Прямые 10 + 10 м и настоящая дуга с выпуклостью 0,5 на хорде 10 м - она длиннее хорды.
    assert line.length > 30
    assert tuple(line.coords[-1]) == pytest.approx((20, 10))
