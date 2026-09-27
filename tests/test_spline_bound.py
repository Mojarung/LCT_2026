"""Сплайн с доказанной погрешностью: не пробел, а полная геометрия.

Кабельная канализация МГТС на Песчаном нарисована сплайнами: 621 сплайн шёл пробелом
«погрешность не ограничена» и остановил бы строгий прогон. Нерациональный сплайн - точная
цепочка кривых Безье; кривая лежит в выпуклой оболочке своих контрольных точек, поэтому
дробление, пока они не лягут ближе допуска к хорде, даёт строгую, а не проверенную в середине
отрезка погрешность. Рациональный сплайн (с весами) так не раскладывается и остаётся пробелом.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import numpy as np
import pytest
import shapely

from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

FLATTEN_M = 0.1  # допуск ридера по умолчанию


def _read(tmp_path: Path, add):  # noqa: ANN001, ANN202
    doc = ezdxf.new("R2018")
    doc.layers.add("МГТС_ существ. ККС")
    spline = add(doc.modelspace())
    spline.dxf.layer = "МГТС_ существ. ККС"
    path = tmp_path / "ducts.dxf"
    doc.saveas(path)
    return EzdxfSceneReader().read(path, unit="m"), spline.construction_tool()


@pytest.mark.parametrize("degree", [2, 3])
def test_plain_spline_is_complete_geometry_within_the_tolerance(
    tmp_path: Path, degree: int
) -> None:
    control = [(0, 0), (10, 25), (30, -20), (55, 30), (80, 0), (100, 12)]
    scene, curve = _read(tmp_path, lambda msp: msp.add_open_spline(control, degree=degree))

    assert scene.read_diagnostics.geometry_gaps == ()
    (feature,) = scene.features
    assert feature.geometry_error_m == pytest.approx(FLATTEN_M)
    truth = shapely.points([(p.x, p.y) for p in curve.points(np.linspace(0, curve.max_t, 4000))])
    assert shapely.distance(truth, feature.geometry).max() <= FLATTEN_M + 1e-9


def test_rational_spline_stays_an_explicit_gap(tmp_path: Path) -> None:
    scene, _ = _read(
        tmp_path,
        lambda msp: msp.add_rational_spline(
            [(0, 0), (10, 20), (30, -10), (50, 0)], weights=[1, 3, 0.5, 1]
        ),
    )

    reasons = {g.reason for g in scene.read_diagnostics.geometry_gaps}
    assert reasons == {"approximation-error-not-bounded"}
