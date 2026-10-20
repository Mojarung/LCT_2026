"""Продолжение рядов существующих деревьев их же шагом.

сторонний вход: у проектировщиков главный признак места нового дерева -
ряд существующих; ряд из 4+ деревьев подряд на прямой с шагом 4-12 м продолжается в обе
стороны и в разрывах (ревью 16.10.2026: из троек в облаке деревьев получались тысячи ложных
рядов). Нормы проверяются как у любого кандидата.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import MultiPoint, Point, box

from green.application.params import PlanParams
from green.application.placement import (
    MODE_EXISTING_ROW,
    MODE_LABELS,
    GreedyPlantingStrategy,
    existing_row_candidates,
)
from green.domain.norms import RuleBook
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Species

C = ObjectClass


def _f(kind: ObjectClass, geometry: object, n: int) -> Feature:
    return Feature(SourceRef("t", "t", str(n)), "t", geometry, object_class=kind)


ROW = [_f(C.EXISTING_TREE, Point(10 + 7 * i, 15), i) for i in range(4)]  # 10..31 по y = 15


def _xy(features: list[Feature]) -> list[tuple[float, float]]:
    return sorted(
        (round(c.x, 2), round(c.y, 2)) for c in existing_row_candidates(features, PlanParams())
    )


def test_row_of_four_is_continued_with_its_own_step_both_ways() -> None:
    xy = _xy(ROW)
    assert (38.0, 15.0) in xy
    assert (45.0, 15.0) in xy
    assert (3.0, 15.0) in xy
    assert all(y == pytest.approx(15.0) for _, y in xy)


def test_gap_inside_a_row_is_filled() -> None:
    gappy = [*ROW, _f(C.EXISTING_TREE, Point(45, 15), 9)]  # 10..31, пропуск 38, затем 45
    assert (38.0, 15.0) in _xy(gappy)


def test_three_trees_or_a_scatter_are_not_a_row() -> None:
    assert _xy(ROW[:3]) == []
    scatter = [
        _f(C.EXISTING_TREE, Point(x, y), i) for i, (x, y) in enumerate([(0, 0), (7, 3), (12, -4)])
    ]
    assert _xy(scatter) == []


def test_planted_continuation_is_labelled_as_such() -> None:
    boundary = box(0, 0, 60, 30)
    features = [_f(C.WORK_BOUNDARY, boundary, 100), _f(C.LAWN, boundary, 101), *ROW]
    plan = GreedyPlantingStrategy().plan(
        features,
        (),
        RuleBook({}, (), "synthetic"),
        Species("test", "test", "test", 4),
        PlanParams(
            modes=(MODE_EXISTING_ROW,),
            require_utility_data=False,
            placement_solver="greedy",
            zones=False,
        ),
    )
    on_row = [p for p in plan.placements if MODE_LABELS[MODE_EXISTING_ROW] in p.notes]
    assert on_row
    assert all(p.y == pytest.approx(15.0) for p in on_row)


def test_far_collinear_tree_does_not_stretch_the_row() -> None:
    far = [*ROW, _f(C.EXISTING_TREE, Point(10 + 7 * 43, 15), 50)]  # на прямой, но в 300 м
    xy = _xy(far)
    assert len(xy) <= 2 * 6 + 2
    assert max(x for x, _ in xy) < 31 + 7 * 7


def test_random_cloud_gives_few_candidates() -> None:
    rng = np.random.default_rng(7)
    cloud = [
        _f(C.EXISTING_TREE, Point(*xy), i) for i, xy in enumerate(rng.uniform(0, 200, (400, 2)))
    ]
    assert len(_xy(cloud)) < 100


def test_tree_strip_is_not_a_trunk() -> None:
    strip = [_f(C.EXISTING_TREE, MultiPoint([(x, 50) for x in range(0, 40, 7)]), 70)]
    assert _xy([*ROW, *strip]) == _xy(ROW)
