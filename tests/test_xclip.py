"""Вставка с обрезкой XCLIP: геометрия режется той же рамкой, что показывает CAD.

Ридер пропускал такую вставку целиком - на Академика Понтрягина 7 вставок, то есть весь их
рисунок (25.09.2026). Блок без обрезки взять нельзя: за рамкой он придумал бы грунт и деревья,
которых на плане нет. За рамкой - «скрыто обрезкой», это не потеря: CAD его тоже не показывает.
Инвертированная обрезка (видно всё снаружи рамки) у ezdxf описана неуверенно - остаётся пробелом.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest
from ezdxf.xclip import XClip

from green.infrastructure.cad.census import insert_census
from green.infrastructure.cad.fidelity import fidelity
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path


def _drawing(tmp_path: Path, *, inverted: bool = False) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    tree = doc.blocks.new("DEREVO_1")
    tree.add_circle((0, 0), radius=0.3)
    topo = doc.blocks.new("TOPO")
    topo.add_line((0, 0), (100, 0))
    topo.add_circle((80, 50), radius=2)
    topo.add_lwpolyline([(10, 10), (20, 10), (20, 20)])
    topo.add_blockref("DEREVO_1", (30, 30))
    topo.add_blockref("DEREVO_1", (70, 30))
    insert = doc.modelspace().add_blockref("TOPO", (1000, 2000))
    clip = XClip(insert)
    clip.set_wcs_clipping_path([(1000, 1990), (1050, 2060)])
    if inverted:
        clip.invert_clipping_path(ignore_acad_compatibility=True)
    path = tmp_path / "clipped.dxf"
    doc.saveas(path)
    return path


def test_clipped_insert_is_read_inside_its_frame(tmp_path: Path) -> None:
    scene = EzdxfSceneReader().read(_drawing(tmp_path), unit="m")

    assert scene.read_diagnostics.geometry_gaps == ()
    assert scene.read_diagnostics.outcomes.get("clipped:outside", 0) >= 2
    kinds = {f.source_entity_type: f.geometry for f in scene.features}
    assert kinds["LINE"].length == pytest.approx(50)
    assert kinds["LWPOLYLINE"].length == pytest.approx(20)
    assert [(s.x, s.y) for s in scene.symbols] == [(1030, 2030)]


def test_ink_check_and_census_agree_with_the_clipped_reading(tmp_path: Path) -> None:
    path = _drawing(tmp_path)
    scene = EzdxfSceneReader().read(path, unit="m")

    report = fidelity(ezdxf.readfile(path), scene)
    census = insert_census(ezdxf.readfile(path), unit_m=1.0)

    assert report.misses == ()
    assert [(r.x, r.y) for r in census] == [(1030, 2030)]


def test_inverted_clip_stays_an_explicit_gap(tmp_path: Path) -> None:
    scene = EzdxfSceneReader().read(_drawing(tmp_path, inverted=True), unit="m")

    assert {g.reason for g in scene.read_diagnostics.geometry_gaps} == {
        "XCLIP-inverted-not-applied"
    }
