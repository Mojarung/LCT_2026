"""Прокси-объект (ACAD_PROXY_ENTITY) читается по своей графике, а не выбрасывается.

Объект стороннего приложения (Civil 3D, Map) хранит рядом с данными готовый рисунок. ezdxf не
переносит такие объекты между файлами: склейка Багрицкого остановилась на одном прокси-объекте
в ссылке «Граница работ» (25.09.2026), а ридер отбрасывал его как неподдерживаемый. Рисунок
разбирается на обычные примитивы на слое самого объекта.
"""

from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import ezdxf
from ezdxf import xref
from ezdxf.lldxf.tags import Tags
from ezdxf.lldxf.types import DXFBinaryTag, DXFTag

from green.infrastructure.cad.merge import EzdxfDrawingMerger
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.layouts import BaseLayout

BOUNDARY = [(0, 0), (50, 0), (50, 20), (0, 20), (0, 0)]


def _graphic(points: list[tuple[float, float]]) -> bytes:
    """Рисунок прокси-объекта: заголовок и одна команда «полилиния» (тип 6)."""
    data = struct.pack("<L", len(points)) + b"".join(
        struct.pack("<3d", x, y, 0.0) for x, y in points
    )
    command = struct.pack("<2L", 8 + len(data), 6) + data
    return struct.pack("<2L", 8 + len(command), 1) + command


def _add_proxy(layout: BaseLayout, layer: str, *, graphic: bool = True) -> None:
    proxy = layout.new_entity("ACAD_PROXY_ENTITY", dxfattribs={"layer": layer})
    tags = [DXFTag(100, "AcDbProxyEntity"), DXFTag(90, 498), DXFTag(91, 500), DXFTag(95, 0)]
    if graphic:
        drawing = _graphic(BOUNDARY)
        tags.append(DXFTag(92, len(drawing)))
        tags += [DXFBinaryTag(310, drawing[i : i + 127]) for i in range(0, len(drawing), 127)]
    proxy.acdb_proxy_entity = Tags(tags)  # ty: ignore[unresolved-attribute]


def test_reader_draws_a_proxy_by_its_graphic_on_its_layer(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.layers.add("Граница работ")
    _add_proxy(doc.modelspace(), "Граница работ")
    path = tmp_path / "proxy.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path, unit="m")

    assert scene.read_diagnostics.geometry_gaps == ()
    assert [(f.layer, f.geometry.bounds) for f in scene.features] == [
        ("Граница работ", (0.0, 0.0, 50.0, 20.0))
    ]


def test_proxy_without_graphic_stays_an_explicit_gap(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    _add_proxy(doc.modelspace(), "0", graphic=False)
    path = tmp_path / "proxy.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path, unit="m")

    assert {g.reason for g in scene.read_diagnostics.geometry_gaps} == {
        "unsupported-spatial-entity"
    }


def test_kit_merge_keeps_a_proxy_in_a_reference_as_its_graphic(tmp_path: Path) -> None:
    boundary = ezdxf.new("R2018")
    boundary.header["$INSUNITS"] = 6
    boundary.layers.add("Граница работ")
    _add_proxy(boundary.modelspace(), "Граница работ")
    boundary.saveas(tmp_path / "boundary.dxf")
    host = ezdxf.new("R2018")
    host.header["$INSUNITS"] = 6
    host.modelspace().add_line((0, 0), (60, 0))
    xref.attach(host, block_name="boundary", filename="boundary.dxf", insert=(0, 0))
    host.saveas(tmp_path / "host.dxf")
    target = tmp_path / "kit.dxf"

    result = EzdxfDrawingMerger().merge([tmp_path / "host.dxf", tmp_path / "boundary.dxf"], target)

    assert any("ACAD_PROXY_ENTITY" in note for note in result.notes)
    scene = EzdxfSceneReader().read(target, unit="m")
    drawn = [f for f in scene.features if f.layer.endswith("Граница работ")]
    assert [f.geometry.bounds for f in drawn] == [(0.0, 0.0, 50.0, 20.0)]
