"""Существующие насаждения чертежа: стволы из знаков и меток, полосы, кусты, граница."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import LineString, MultiPoint, Point, box

from green.application.quality import site_of
from green.application.stock import EMPTY_STOCK, stock_of
from green.application.tree_strips import STRIP_SOURCE
from green.domain.objects import Feature, ObjectClass, SourceRef

BOUNDARY = box(0.0, 0.0, 100.0, 40.0)
_counter = iter(range(10_000))


def _f(geometry, cls: ObjectClass, **kw) -> Feature:  # noqa: ANN001, ANN003 - фабрика теста
    return Feature(
        SourceRef("f", "x", str(next(_counter))), "слой", geometry, object_class=cls, **kw
    )


def _boundary() -> Feature:
    return _f(BOUNDARY, ObjectClass.WORK_BOUNDARY)


def _symbol(x: float, y: float, ref: str) -> Feature:
    return _f(Point(x, y), ObjectClass.EXISTING_TREE, symbol=ref, source_entity_type="SYMBOL")


def _strokes(x: float, y: float, count: int = 30) -> list[Feature]:
    """Разобранный знак дерева: дуги и отрезки вокруг ствола в пределах 0,4 м."""
    out = []
    for k in range(count):
        a = 2 * math.pi * k / count
        cx, cy = x + 0.3 * math.cos(a), y + 0.3 * math.sin(a)
        out.append(
            _f(
                LineString([(cx, cy), (cx + 0.05, cy + 0.05)]),
                ObjectClass.EXISTING_TREE,
                source_entity_type="ARC",
            )
        )
    return out


def test_symbols_and_strokes_become_trunks() -> None:
    features = [
        _boundary(),
        _symbol(10.0, 10.0, "s1"),
        _symbol(30.0, 10.0, "s2"),
        *_strokes(50.0, 10.0),
    ]
    stock = stock_of(features, BOUNDARY, crown_m=8.0)
    assert stock.trees == 3
    assert stock.source == "mixed"
    assert stock.marks == 32
    assert stock.trees_radius.tolist() == pytest.approx([4.0, 4.0, 4.0])


def test_strokes_of_a_symbol_join_its_trunk() -> None:
    features = [_boundary(), _symbol(10.0, 10.0, "s1"), *_strokes(10.2, 10.1)]
    assert stock_of(features, BOUNDARY, crown_m=8.0).trees == 1


def test_marks_further_than_a_metre_are_two_trees() -> None:
    features = [_boundary(), *_strokes(10.0, 10.0), *_strokes(11.7, 10.0)]
    assert stock_of(features, BOUNDARY, crown_m=8.0).trees == 2


def test_tree_strip_is_not_a_trunk() -> None:
    strip = _f(
        MultiPoint([(20.0 + i, 20.0) for i in range(10)]),
        ObjectClass.EXISTING_TREE,
        source_entity_type=STRIP_SOURCE,
    )
    stock = stock_of([_boundary(), strip], BOUNDARY, crown_m=8.0)
    assert stock.trees == 0
    assert len(stock.strips_xy) == 10
    assert len(stock.crowns()[0]) == 0
    assert stock.canopy is None


def test_trunk_outside_counts_only_when_its_crown_reaches_the_site() -> None:
    features = [_boundary(), _symbol(-3.0, 10.0, "near"), _symbol(-30.0, 10.0, "far")]
    stock = stock_of(features, BOUNDARY, crown_m=8.0)
    assert stock.trees == 0
    assert len(stock.trees_xy) == 1
    assert stock.inside.tolist() == [False]


def test_shrubs_inside_the_site() -> None:
    features = [
        _boundary(),
        _f(Point(5.0, 5.0), ObjectClass.EXISTING_SHRUB),
        _f(Point(-50.0, 5.0), ObjectClass.EXISTING_SHRUB),
    ]
    assert stock_of(features, BOUNDARY, crown_m=8.0).shrubs == 1


def test_no_boundary_no_stock() -> None:
    assert stock_of([_symbol(1.0, 1.0, "s")], None, crown_m=8.0) is EMPTY_STOCK


def test_site_carries_the_stock() -> None:
    site = site_of([_boundary(), _symbol(10.0, 10.0, "s1")], crown_m=6.0)
    assert site.stock.trees == 1
    assert site.stock.trees_radius.tolist() == [3.0]


def test_crowns_merge_pseudo_trunks_of_one_tree() -> None:
    """Метки одного дерева в 1,7 м друг от друга - два ствола при 1 м, но одна крона."""
    stock = stock_of(
        [_boundary(), *_strokes(10.0, 10.0), *_strokes(11.7, 10.0)], BOUNDARY, crown_m=8.0
    )
    assert stock.trees == 2
    assert int(stock.crown_inside.sum()) == 1
