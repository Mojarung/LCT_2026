"""Сборка улицы обратно: всё, что CAD нарисовал бы, должно найтись в разобранной сцене.

Учёт исходов считает примитивы, но не доказывает, что геометрия цела. Сверка рисует исходник
тем же движком, что строит картинку чертежа, и ищет чернила, рядом с которыми в сцене нет
объекта: это и есть тихая потеря ридера.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import ezdxf
import pytest

from green.infrastructure.cad.fidelity import fidelity
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path


def _drawing(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    handles = {
        "line": msp.add_line((0, 0), (12, 0)).dxf.handle,
        "circle": msp.add_circle((30, 5), radius=2).dxf.handle,
        "arc": msp.add_arc((40, 5), radius=3, start_angle=0, end_angle=120).dxf.handle,
        "polyline": msp.add_lwpolyline([(0, 10), (10, 10), (10, 20)]).dxf.handle,
        "wide": msp.add_lwpolyline(
            [(20, 20), (35, 20)], dxfattribs={"const_width": 1.0}
        ).dxf.handle,
    }
    hatch = msp.add_hatch()
    hatch.paths.add_polyline_path([(50, 0), (60, 0), (60, 8), (50, 8)], is_closed=True)
    handles["hatch"] = hatch.dxf.handle
    block = doc.blocks.new("KOLOD_1")
    block.add_circle((0, 0), radius=0.5)
    block.add_line((-0.5, 0), (0.5, 0))
    handles["insert"] = msp.add_blockref("KOLOD_1", (70, 5), dxfattribs={"rotation": 30}).dxf.handle
    dimension = msp.add_linear_dim(base=(0, -3), p1=(0, 0), p2=(12, 0))
    dimension.render()
    handles["dimension"] = dimension.dimension.dxf.handle
    path = tmp_path / "street.dxf"
    doc.saveas(path)
    return path, handles


def test_complete_scene_leaves_no_ink_behind(tmp_path: Path) -> None:
    path, _ = _drawing(tmp_path)
    scene = EzdxfSceneReader().read(path, unit="m")

    report = fidelity(ezdxf.readfile(path), scene)

    assert report.ink_m > 100
    assert report.missed_m == pytest.approx(0, abs=0.05)
    assert report.misses == ()
    assert report.windows
    assert max(w.missed_m for w in report.windows) == pytest.approx(0, abs=0.05)


def test_lost_segment_is_reported_with_its_length_and_handle(tmp_path: Path) -> None:
    path, handles = _drawing(tmp_path)
    scene = EzdxfSceneReader().read(path, unit="m")
    without = replace(
        scene, features=tuple(f for f in scene.features if f.ref.handle != handles["line"])
    )

    report = fidelity(ezdxf.readfile(path), without)

    assert report.missed_m == pytest.approx(12, abs=0.2)
    assert [(m.handle, m.entity_type) for m in report.misses] == [(handles["line"], "LINE")]
    assert report.misses[0].missed_m == pytest.approx(12, abs=0.2)


def test_wide_polyline_is_covered_by_its_axis_and_counted(tmp_path: Path) -> None:
    """Ридер хранит ось полилинии; контур ширины 1 м - в 0,5 м от оси, дальше допуска."""
    path, handles = _drawing(tmp_path)
    scene = EzdxfSceneReader().read(path, unit="m")

    report = fidelity(ezdxf.readfile(path), scene)

    assert handles["wide"] not in {m.handle for m in report.misses}
    assert report.wide_polylines == 1


def test_annotation_ink_is_kept_apart_from_drawing_ink(tmp_path: Path) -> None:
    path, handles = _drawing(tmp_path)
    scene = EzdxfSceneReader().read(path, unit="m")

    report = fidelity(ezdxf.readfile(path), scene)

    assert handles["dimension"] not in {m.handle for m in report.misses}
    assert report.annotation_ink_m > 0
