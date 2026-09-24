"""REGION - замкнутая область, форма которой хранится в данных ACIS, а не в DXF-геометрии.

В выгрузках Мосгеотреста так записаны газоны, ограды, лестницы и участки сетей. Без разбора
ACIS эти области терялись целиком: на Старом Гае 12 180, на Академика Понтрягина 33 339
(перепись 24.09.2026, docs/plans/2026-09-24-lossless-reader-plan.md).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.acis import api as acis
from ezdxf.render.mesh import MeshBuilder

from green.infrastructure.cad.acis_region import RegionGeometryError, region_polygon
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.layouts import BaseLayout

SIDE = 10.0
ARC_SAT = (
    "400 0 1 0",
    "9 test tool 8 ACIS 4.0 24 Thu Sep 24 12:00:00 2026",
    "25.4 9.9999999999999995e-07 1e-10",
    "body $-1 $1 $-1 $-1 #",
    "lump $-1 $-1 $2 $0 #",
    "shell $-1 $-1 $-1 $3 $-1 $1 #",
    "face $-1 $-1 $4 $2 $-1 $5 forward single #",
    "loop $-1 $-1 $6 $3 #",
    "plane-surface $-1 0 0 0 0 0 1 1 0 0 forward_v I I I I #",
    "coedge $-1 $7 $7 $-1 $8 forward $4 $-1 #",
    "coedge $-1 $6 $6 $-1 $9 forward $4 $-1 #",
    "edge $-1 $10 $11 $6 $12 forward #",
    "edge $-1 $11 $10 $7 $13 forward #",
    "vertex $-1 $8 $14 #",
    "vertex $-1 $9 $15 #",
    "ellipse-curve $-1 0 0 0 0 0 1 5 0 0 1 I I #",
    "straight-curve $-1 -5 0 0 1 0 0 I I #",
    "point $-1 5 0 0 #",
    "point $-1 -5 0 0 #",
)


def _square_region(layout: BaseLayout) -> None:
    mesh = MeshBuilder()
    mesh.add_face([(0, 0, 0), (SIDE, 0, 0), (SIDE, SIDE, 0), (0, SIDE, 0)])
    region = layout.add_region(dxfattribs={"layer": "Леса и газоны"})
    acis.export_dxf(region, [acis.body_from_mesh(mesh)])


def test_square_region_becomes_its_polygon() -> None:
    doc = ezdxf.new("R2000")
    _square_region(doc.modelspace())
    region = doc.modelspace().query("REGION").first

    polygon, error = region_polygon(region, None, 0.1)

    assert polygon.area == pytest.approx(SIDE * SIDE)
    assert polygon.bounds == pytest.approx((0, 0, SIDE, SIDE))
    assert error == 0.0


def test_region_inside_a_rotated_insert_lands_in_world_coordinates(tmp_path: Path) -> None:
    doc = ezdxf.new("R2000")
    block = doc.blocks.new("LAWN_PATCH")
    _square_region(block)
    doc.modelspace().add_blockref("LAWN_PATCH", (100, 50), dxfattribs={"rotation": 90})
    path = tmp_path / "rotated.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path)

    regions = [f for f in scene.features if f.source_entity_type == "REGION"]
    assert len(regions) == 1
    assert regions[0].geometry.area == pytest.approx(SIDE * SIDE)
    assert regions[0].geometry.centroid.x == pytest.approx(100 - SIDE / 2)
    assert regions[0].geometry.centroid.y == pytest.approx(50 + SIDE / 2)
    assert not scene.read_diagnostics.geometry_gaps


def test_region_without_acis_data_stays_a_named_gap(tmp_path: Path) -> None:
    """Так её оставляет LibreDWG для DWG 2018: теги есть, данных ACIS нет. ezdxf такую не пишет."""
    doc = ezdxf.new("R2018")
    doc.layers.add("Газопровод")
    path = tmp_path / "empty.dxf"
    doc.saveas(path)
    data = path.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    marker = "  2\nENTITIES\n"
    region = (
        "  0\nREGION\n  5\nAFF123\n100\nAcDbEntity\n  8\nГазопровод\n"
        "100\nAcDbModelerGeometry\n 70\n1\n100\nAcDbRegion\n"
    )
    path.write_bytes(data.replace(marker, marker + region, 1).encode("utf-8"))

    scene = EzdxfSceneReader().read(path)

    gaps = scene.read_diagnostics.geometry_gaps
    assert [(g.entity_type, g.reason, g.count) for g in gaps] == [
        ("REGION", "missing-acis-data", 1)
    ]
    assert not scene.features


def test_arc_edges_are_flattened_within_tolerance() -> None:
    """Полукруг радиусом 5: дуга ellipse-curve и хорда straight-curve по диаметру."""
    doc = ezdxf.new("R2000")
    region = doc.modelspace().add_region()
    region.sat = list(ARC_SAT)
    tolerance = 0.01

    polygon, error = region_polygon(region, None, tolerance)

    half_disc = math.pi * 25 / 2
    assert polygon.area == pytest.approx(half_disc, rel=0.01)
    assert polygon.area <= half_disc
    assert polygon.bounds == pytest.approx((-5, 0, 5, 5), abs=tolerance)
    assert error == pytest.approx(tolerance)


def test_asm_sat_with_pointer_ids_is_read() -> None:
    """ASM AutoCAD (SAT 21200, DXF 2007): второе поле записи - «$-1» вместо «-1».

    Так записаны сети Песчаного переулка; ezdxf ждёт число и падал на первой записи.
    """
    doc = ezdxf.new("R2000")
    _square_region(doc.modelspace())
    region = doc.modelspace().query("REGION").first
    lines = list(region.sat)
    asm = [lines[0].replace("700", "21200", 1), *lines[1:3]]
    for line in lines[3:]:
        tokens = line.split(" ")
        if len(tokens) > 2 and tokens[2] == "-1":
            tokens[2] = "$-1"
        asm.append(" ".join(tokens))
    region.sat = asm

    polygon, _ = region_polygon(region, None, 0.1)

    assert polygon.area == pytest.approx(SIDE * SIDE)


def test_unparseable_acis_is_a_reasoned_error() -> None:
    doc = ezdxf.new("R2000")
    region = doc.modelspace().add_region()
    region.sat = ["700 0 1 0", "@4 test @4 ACIS @4 date", "1 1e-06 1e-10", "body broken #"]

    with pytest.raises(RegionGeometryError) as caught:
        region_polygon(region, None, 0.1)

    assert caught.value.reason.startswith("acis-not-parsed")


def test_region_without_data_raises_a_reasoned_error() -> None:
    doc = ezdxf.new("R2000")
    region = doc.modelspace().add_region()

    with pytest.raises(RegionGeometryError) as caught:
        region_polygon(region, None, 0.1)

    assert caught.value.reason == "missing-acis-data"
