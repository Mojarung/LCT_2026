"""Мультивыноска с полкой нулевой длины не роняет разбор вставки.

ezdxf 1.4.4 нормализует нулевой вектор полки при переносе вставки и падает с делением на
ноль: ридер объявлял всю вставку неразбираемой (одна выноска - весь рисунок внешней ссылки),
сверка чернил падала целиком (улица Берзарина, 25.09.2026).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
from ezdxf.math import Vec2, Vec3
from ezdxf.render import mleader

from green.infrastructure.cad.fidelity import fidelity
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path


def _drawing(tmp_path: Path) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    block = doc.blocks.new("NOTE")
    block.add_line((0, 0), (20, 0))
    builder = block.add_multileader_mtext("Standard")
    builder.set_content("Т2 ду200")
    builder.add_leader_line(mleader.ConnectionSide.left, [Vec2(-5, -5)])
    builder.build(insert=Vec2(0, 0))
    leader = builder.multileader.context.leaders[0]
    leader.dogleg_length = 0.0
    leader.dogleg_vector = Vec3()
    doc.modelspace().add_blockref("NOTE", (100, 100), dxfattribs={"rotation": 30})
    path = tmp_path / "note.dxf"
    doc.saveas(path)
    return path


def test_insert_with_a_zero_dogleg_leader_is_read_whole(tmp_path: Path) -> None:
    scene = EzdxfSceneReader().read(_drawing(tmp_path), unit="m")

    assert "insert:not-explodable" not in scene.read_diagnostics.outcomes
    assert [f.source_entity_type for f in scene.features] == ["LINE"]


def test_ink_check_draws_a_zero_dogleg_leader(tmp_path: Path) -> None:
    path = _drawing(tmp_path)
    scene = EzdxfSceneReader().read(path, unit="m")

    report = fidelity(ezdxf.readfile(path), scene)

    assert report.misses == ()
    assert report.ink_m > 19
