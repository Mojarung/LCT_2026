"""Центры групп кустарника на газоне: проверка точек по мере надобности, а не всех сразу.

Профиль Камчатской 17.10.2026: _centers проверял нормами каждую точку грунта участка (19 с),
хотя групп нужно несколько десятков и обход идёт от борта вглубь. Порядок обхода и ответ те же.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely.geometry import LineString

from green.application import shrub_fill
from green.application.params import PlanParams
from green.application.surfaces import Material
from green.domain.planting import Plan, Verdict

if TYPE_CHECKING:
    import pytest


@dataclass
class _Index:
    """Индекс ограничений: всё допустимо, кроме полосы x < 3 м; считает проверенные точки."""

    surface: SimpleNamespace
    evaluated: int = 0
    calls: list[int] = field(default_factory=list)

    def plantable(self, points: np.ndarray) -> np.ndarray:
        return np.ones(len(points), dtype=bool)

    def evaluate(self, points: np.ndarray) -> SimpleNamespace:
        self.evaluated += len(points)
        self.calls.append(len(points))
        xs = shapely.get_x(points)
        return SimpleNamespace(
            verdict=lambda row: Verdict.ALLOWED if xs[row] >= 3.0 else Verdict.FORBIDDEN
        )


def _index() -> _Index:
    grid = np.full((300, 300), Material.SOIL, dtype=np.int8)
    return _Index(SimpleNamespace(grid=grid, cell=1.0, origin=(0.0, 0.0)))


def _run(index: _Index, groups: int) -> list[tuple[float, float]]:
    curb = [LineString([(0, 0), (0, 300)])]
    empty = Plan(placements=(), rejections=())
    return shrub_fill._centers(empty, index, PlanParams(), groups, curb)  # noqa: SLF001


def test_only_points_up_to_the_needed_groups_are_checked() -> None:
    index = _index()
    centers = _run(index, groups=10)
    assert len(centers) == 10
    assert index.evaluated < 300 * 300 / 4  # раньше - все 90 000 точек грунта


def test_lazy_check_gives_the_same_centers_as_checking_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lazy = _run(_index(), groups=25)
    monkeypatch.setattr(shrub_fill, "CENTER_CHUNK", 10**9)
    full = _run(_index(), groups=25)
    assert lazy == full
    assert all(x >= 3.0 for x, _ in lazy)
