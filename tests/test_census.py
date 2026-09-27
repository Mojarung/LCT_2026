"""Перепись вставок-знаков своим обходом совпадает с экземплярами ридера.

Ридер находит знаки по ходу общего разбора; перепись считает их заново матрицами вставок.
Два независимых счёта одних и тех же деревьев - доказательство, что ни одно не потерялось
и не удвоилось (обёртка MicroStation, поворот, вставка массивом).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest

from green.infrastructure.cad.census import insert_census
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path


def _street(tmp_path: Path) -> Path:
    doc = ezdxf.new("R2018")
    tree = doc.blocks.new("DEREVO_935", base_point=(0.5, 0.5))
    tree.add_circle((0.5, 0.5), radius=0.3)
    tree.add_line((0, 0.5), (1, 0.5))
    shrub = doc.blocks.new("KUST1_7")
    shrub.add_circle((0, 0), radius=0.2)
    wrapper = doc.blocks.new("msdElementType12")
    wrapper.add_blockref("DEREVO_935", (10, 0), dxfattribs={"rotation": 45})
    wrapper.add_blockref("KUST1_7", (0, 10), dxfattribs={"layer": "0"})
    msp = doc.modelspace()
    doc.layers.add("Полоса деревьев")
    msp.add_blockref("DEREVO_935", (5, 5), dxfattribs={"layer": "Полоса деревьев"})
    msp.add_blockref(
        "msdElementType12", (100, 200), dxfattribs={"layer": "Полоса деревьев", "rotation": 90}
    )
    array = msp.add_blockref("KUST1_7", (50, 50))
    array.grid(size=(2, 3), spacing=(2, 4))
    path = tmp_path / "street.dxf"
    doc.saveas(path)
    return path


def test_census_matches_reader_instances_by_count_and_points(tmp_path: Path) -> None:
    path = _street(tmp_path)
    scene = EzdxfSceneReader().read(path, unit="m")

    records = insert_census(ezdxf.readfile(path), unit_m=scene.unit_m)

    reader = sorted((s.block, round(s.x, 6), round(s.y, 6), s.layer) for s in scene.symbols)
    census = sorted((r.block, round(r.x, 6), round(r.y, 6), r.layer) for r in records)
    assert len(census) == 1 + 2 + 6
    assert census == reader


def test_census_names_the_symbol_code_and_nesting_depth(tmp_path: Path) -> None:
    records = insert_census(ezdxf.readfile(_street(tmp_path)), unit_m=1.0)

    nested = [r for r in records if r.depth == 1]
    assert sorted(r.base for r in nested) == ["DEREVO", "KUST1"]
    tree = next(r for r in nested if r.base == "DEREVO")
    assert (tree.x, tree.y) == pytest.approx((100, 210))
