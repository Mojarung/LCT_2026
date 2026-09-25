"""Размер дугой - оформление, мультилиния - линии на земле, а не пробел чтения.

Харьковский проезд (25.09.2026): 105 размеров ARC_DIMENSION ридер записывал пробелами чтения,
хотя это такое же оформление, как DIMENSION, и строгий прогон останавливался. Берзарина:
47 футляров кабелей освещения нарисованы мультилиниями MLINE - это линии объекта.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest
import shapely

from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path


def test_arc_dimension_is_annotation_not_a_gap(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "Бортовой камень"})
    msp.add_arc_dim_3p(
        base=(5, 8), center=(0, 0), p1=(5, 0), p2=(0, 5), dxfattribs={"layer": "Размеры"}
    ).render()
    path = tmp_path / "arc_dimension.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path)

    diagnostics = scene.read_diagnostics
    assert not diagnostics.geometry_gaps
    assert diagnostics.visited_by_type["ARC_DIMENSION"] == 1
    assert [f.layer for f in scene.features] == ["Бортовой камень"]


def test_mline_is_read_as_its_lines_on_its_layer(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    mline = msp.add_mline([(0, 0), (10, 0), (10, 5)], dxfattribs={"layer": "ЭН_трубы"})
    # Как рисует CAD: две линии стиля Standard вдоль каждого участка оси.
    drawn = shapely.union_all(
        [
            shapely.LineString([(e.dxf.start.x, e.dxf.start.y), (e.dxf.end.x, e.dxf.end.y)])
            for e in mline.virtual_entities()
        ]
    )
    path = tmp_path / "mline.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path)

    assert not scene.read_diagnostics.geometry_gaps
    assert {f.layer for f in scene.features} == {"ЭН_трубы"}
    assert len(scene.features) == 4
    lines = shapely.union_all([f.geometry for f in scene.features])
    assert lines.length == pytest.approx(drawn.length)
    assert lines.hausdorff_distance(drawn) == pytest.approx(0.0, abs=1e-9)


def test_picture_underlays_are_accounted_not_gaps(tmp_path: Path) -> None:
    """Растр карты или спутника и маска WIPEOUT - картинка под чертежом, а не объект съёмки:
    учёт исходов их показывает, прогон они не останавливают (решение 25.09.2026)."""
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    image_def = doc.add_image_def(filename="sputnik.png", size_in_pixel=(640, 480))
    msp.add_image(image_def, insert=(0, 0), size_in_units=(64, 48), dxfattribs={"layer": "Спутник"})
    msp.add_wipeout([(0, 0), (5, 0), (5, 5), (0, 5)], dxfattribs={"layer": "Листы"})
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "Бортовой камень"})
    path = tmp_path / "underlay.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path)

    diagnostics = scene.read_diagnostics
    assert not diagnostics.geometry_gaps
    assert diagnostics.outcomes["skipped:IMAGE:underlay"] == 1
    assert diagnostics.outcomes["skipped:WIPEOUT:underlay"] == 1
    assert [f.layer for f in scene.features] == ["Бортовой камень"]
