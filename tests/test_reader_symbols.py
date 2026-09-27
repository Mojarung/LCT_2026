"""Условные знаки: вставка блока-знака - один объект с точкой вставки, её примитивы - штрихи.

Дерево на подоснове Мосгеотреста - блок DEREVO из эллипса, круга и линии. Ридер разбирал его
на три отдельных объекта без общего владельца: на Кустанайской из 1 834 деревьев получалось
5 501 «дерево». Знак должен остаться одним объектом, а каждый посещённый примитив - получить
ровно один исход в учёте чтения, чтобы потерю было видно числом.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import ezdxf
import pytest

from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing


def _tree_block(doc: Drawing, name: str) -> None:
    """Знак дерева: эллипс кроны, круг ствола и линия, всего три примитива."""
    block = doc.blocks.new(name)
    block.add_ellipse((0, 0), major_axis=(1, 0), ratio=0.5)
    block.add_circle((0, 0), radius=0.5)
    block.add_line((-0.5, 0), (0.5, 0))


def _read(doc: Drawing, tmp_path: Path, *, unit: str = "m"):  # noqa: ANN202 - Scene
    path = tmp_path / "symbols.dxf"
    doc.saveas(path)
    return EzdxfSceneReader().read(path, unit=unit)


def test_each_symbol_insert_is_one_instance_owning_its_strokes(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    points = [(1000, 2000), (3000, 4000), (5000, 6000)]
    for number, point in enumerate(points, start=1):
        _tree_block(doc, f"DEREVO_{number}")
        doc.modelspace().add_blockref(
            f"DEREVO_{number}", point, dxfattribs={"layer": "Полоса деревьев", "rotation": 30}
        )

    scene = _read(doc, tmp_path, unit="mm")

    assert [(s.block, s.x, s.y) for s in scene.symbols] == [
        ("DEREVO_1", 1.0, 2.0),
        ("DEREVO_2", 3.0, 4.0),
        ("DEREVO_3", 5.0, 6.0),
    ]
    assert {s.layer for s in scene.symbols} == {"Полоса деревьев"}
    assert {s.rotation_deg for s in scene.symbols} == {30.0}
    assert [s.strokes for s in scene.symbols] == [3, 3, 3]
    owners = Counter(feature.symbol for feature in scene.features)
    assert owners == {str(symbol.ref): 3 for symbol in scene.symbols}
    assert scene.read_diagnostics.outcomes["insert:symbol"] == 3


def test_symbol_inside_an_msd_wrapper_is_the_instance_not_the_wrapper(tmp_path: Path) -> None:
    """MicroStation-обёртка msdElementType_* - контейнер: знак внутри неё остаётся знаком."""
    doc = ezdxf.new("R2018")
    _tree_block(doc, "DEREVO")
    wrapper = doc.blocks.new("msdElementType_5")
    wrapper.add_blockref("DEREVO", (10, 20))
    doc.modelspace().add_blockref("msdElementType_5", (100, 200))

    scene = _read(doc, tmp_path)

    assert [(s.block, s.x, s.y) for s in scene.symbols] == [("DEREVO", 110.0, 220.0)]
    assert scene.read_diagnostics.outcomes["insert:container"] == 1
    assert scene.read_diagnostics.outcomes["insert:symbol"] == 1


def test_dimtxt_is_a_container_and_its_text_has_no_owner(tmp_path: Path) -> None:
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("DIMTXT_7")
    block.add_text("300", dxfattribs={"insert": (0, 0)})
    block.add_leader([(0, 0), (5, 5)])
    doc.modelspace().add_blockref("DIMTXT_7", (50, 50))

    scene = _read(doc, tmp_path)

    assert not scene.symbols
    assert [(label.text, label.symbol) for label in scene.labels] == [("300", None)]
    assert scene.read_diagnostics.outcomes["insert:container"] == 1


@pytest.mark.parametrize(
    ("contents", "why"),
    [("big", "габарит больше 12 м"), ("many", "больше 64 примитивов"), ("empty", "пустой блок")],
)
def test_large_crowded_or_empty_blocks_are_containers(
    tmp_path: Path, contents: str, why: str
) -> None:
    doc = ezdxf.new("R2018")
    block = doc.blocks.new("PLANSHET")
    if contents == "big":
        block.add_line((0, 0), (20, 0))
    elif contents == "many":
        for x in range(65):
            block.add_point((x * 0.01, 0))
    doc.modelspace().add_blockref("PLANSHET", (0, 0))

    scene = _read(doc, tmp_path)

    assert not scene.symbols, why
    assert scene.read_diagnostics.outcomes["insert:container"] == 1, why


def test_every_visited_entity_has_exactly_one_outcome(tmp_path: Path) -> None:
    """Учёт чтения: текст, пустой текст, подпись без точки выравнивания, знак, MINSERT,
    вложенная вставка внутри знака, выноска - каждое посещение ровно с одним исходом."""
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    msp.add_text("подпись", dxfattribs={"insert": (0, 0)})
    msp.add_text("   ", dxfattribs={"insert": (1, 1)})
    msp.add_text("ГАЗОН", dxfattribs={"insert": (10, 10), "halign": 1})
    _tree_block(doc, "KUST1")
    msp.add_blockref("KUST1", (5, 5))
    msp.add_blockref("KUST1", (20, 20)).grid(size=(2, 3), spacing=(3, 3))
    nested = doc.blocks.new("KUST_GROUP")
    nested.add_blockref("KUST1", (0, 0))
    nested.add_circle((0, 0), radius=1)
    msp.add_blockref("KUST_GROUP", (40, 40))
    msp.add_leader([(0, 0), (5, 5)])

    scene = _read(doc, tmp_path)

    diagnostics = scene.read_diagnostics
    assert sum(diagnostics.outcomes.values()) == sum(diagnostics.visited_by_type.values())
    assert diagnostics.outcomes["label"] == 1
    assert diagnostics.outcomes["label:empty"] == 1
    assert diagnostics.outcomes["skipped:TEXT:text-alignment-point-missing"] == 1
    assert diagnostics.outcomes["insert:multi"] == 1
    assert diagnostics.outcomes["insert:in-symbol"] == 1
    assert diagnostics.outcomes["skipped:LEADER:annotation"] == 1
    # KUST1, шесть экземпляров MINSERT и группа кустов: знаки по вставкам верхнего уровня.
    assert len(scene.symbols) == 8
