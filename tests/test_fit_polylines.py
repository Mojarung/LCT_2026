"""Полилиния, сглаженная сплайном: на экране CAD - вершины сглаживания, а не рамка.

Такая 2D-полилиния хранит рядом вершины сглаживания (флаг 8) и вершины рамки (флаг 16).
AutoCAD рисует только первые, ezdxf строит путь по всем подряд - зигзаг между кривой и
рамкой. Ридер помечал такие полилинии «погрешность не ограничена», и строгий прогон стоял
(Куликовская 617, 3-я Парковая 775). Нарисованное - ломаная по вершинам сглаживания, точно.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import shapely
from ezdxf.render.r12spline import R12Spline

from green.infrastructure.cad.fidelity import fidelity
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

FRAME = [(0, 0), (10, 30), (30, -30), (50, 30), (70, 0)]


def _drawing(tmp_path: Path) -> tuple[Path, list[tuple[float, float]], list[tuple[float, float]]]:
    doc = ezdxf.new("R2018")
    polyline = R12Spline(FRAME, degree=3, closed=False).render(doc.modelspace(), segments=40)
    fitted = [(v.dxf.location.x, v.dxf.location.y) for v in polyline.vertices if v.dxf.flags & 8]
    frame = [(v.dxf.location.x, v.dxf.location.y) for v in polyline.vertices if v.dxf.flags & 16]
    path = tmp_path / "fit.dxf"
    doc.saveas(path)
    return path, fitted, frame


def test_spline_fit_polyline_is_its_fitted_vertices(tmp_path: Path) -> None:
    path, fitted, frame = _drawing(tmp_path)
    assert fitted
    assert frame

    scene = EzdxfSceneReader().read(path, unit="m")

    assert scene.read_diagnostics.geometry_gaps == ()
    (feature,) = scene.features
    assert feature.geometry_error_m == 0.0
    assert [tuple(p) for p in feature.geometry.coords] == fitted
    inner_frame = shapely.points(frame[1:-1])
    assert shapely.distance(inner_frame, feature.geometry).min() > 1.0


def test_ink_check_draws_the_fitted_curve_without_the_frame(tmp_path: Path) -> None:
    path, _, _ = _drawing(tmp_path)
    scene = EzdxfSceneReader().read(path, unit="m")

    report = fidelity(ezdxf.readfile(path), scene)

    assert report.misses == ()


def test_curve_fit_polyline_is_its_bulged_vertices(tmp_path: Path) -> None:
    """Сглаживание дугами (PEDIT Fit) пишет дуги выпуклостями вершин, добавленные вершины -
    флаг 1: CAD рисует ту же ломаную с дугами. Знак разметки 1.24.3 Куликовской вставлен 617
    раз и каждый раз шёл пробелом «погрешность не ограничена»."""
    doc = ezdxf.new("R2018")
    polyline = doc.modelspace().add_polyline2d(
        [(0, 0, 0.4), (10, 0, 0), (10, 10, -0.3), (0, 10, 0)], format="xyb", close=True
    )
    polyline.dxf.flags |= 2
    for vertex in list(polyline.vertices)[1::2]:
        vertex.dxf.flags |= 1
    path = tmp_path / "curve_fit.dxf"
    doc.saveas(path)

    scene = EzdxfSceneReader().read(path, unit="m")

    assert scene.read_diagnostics.geometry_gaps == ()
    (feature,) = scene.features
    assert feature.geometry_error_m is not None
    assert feature.geometry_error_m <= 0.1
