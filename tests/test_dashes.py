"""Пунктир в DXF: штрихи одной линии сшиваются обратно, прерывистый тип линии - флаг dashed."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ezdxf
import pytest
from shapely.geometry import LineString, Point

from green.domain.objects import Feature, SourceRef
from green.infrastructure.cad.dashes import chain_dashes
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from pathlib import Path

PARENT = "2A"
CURB = "Бортовой камень"


def _piece(index: int, coords: list[tuple[float, float]], layer: str = CURB) -> Feature:
    return Feature(
        SourceRef("f", "c", f"{PARENT}~{index}"),
        layer,
        LineString(coords),
        block="msdElementTypeLineString_1",
        source_entity_type="LINE",
    )


def _dashes(
    path: list[tuple[float, float]], dash: float = 0.75, gap: float = 0.5
) -> list[list[tuple[float, float]]]:
    """Штрихи вдоль ломаной так, как их пишет MicroStation: шаг по длине пути."""
    line = LineString(path)
    pieces, at = [], 0.0
    while at < line.length:
        end = min(at + dash, line.length)
        cut = [line.interpolate(at)]
        cut += [Point(c) for c in line.coords if at < line.project(Point(c)) < end]
        cut.append(line.interpolate(end))
        pieces.append([(p.x, p.y) for p in cut])
        at = end + gap
    return pieces


def test_dashes_of_a_straight_curb_become_one_line() -> None:
    # 16 штрихов по 0,75 м через 0,5 м: от начала первого до конца последнего 19,5 м.
    pieces = [_piece(i, c) for i, c in enumerate(_dashes([(0, 0), (19.5, 0)]))]
    assert len(pieces) == 16
    out = chain_dashes(pieces, parent=PARENT)
    assert len(out) == 1
    assert out[0].dashed
    assert out[0].ref == pieces[0].ref
    assert out[0].geometry.length == pytest.approx(19.5, abs=0.01)


def test_a_corner_inside_a_gap_is_restored_exactly() -> None:
    """Вершина ломаной попала в разрыв: прямая перемычка срезала бы угол, а штрихи по обе
    стороны продолжаются до точной вершины."""
    path = [(0, 0), (9.75, 0), (9.75, 8)]
    pieces = [_piece(i, c) for i, c in enumerate(_dashes(path))]
    assert all(p.geometry.distance(Point(9.75, 0)) > 0.2 for p in pieces)  # вершина в разрыве
    out = chain_dashes(pieces, parent=PARENT)
    assert len(out) == 1
    assert (9.75, 0) in out[0].geometry.coords
    assert out[0].geometry.length == pytest.approx(LineString(path).length, abs=0.02)


def test_a_dashed_shape_closes_into_a_ring() -> None:
    square = [(0, 0), (6, 0), (6, 6), (0, 6), (0, 0)]
    pieces = [_piece(i, c) for i, c in enumerate(_dashes(square, dash=0.7, gap=0.5))]
    out = chain_dashes(pieces, parent=PARENT)
    assert len(out) == 1
    ring = out[0].geometry
    assert ring.is_closed
    assert ring.length == pytest.approx(24.0, abs=0.05)


def test_slope_ticks_and_dot_fills_are_not_chained() -> None:
    """Бергштрихи откоса параллельны: конец одного не смотрит на начало другого."""
    ticks = [_piece(i, [(i * 0.5, 0.0), (i * 0.5, 1.0 if i % 2 else 0.5)]) for i in range(6)]
    assert chain_dashes(ticks, parent=PARENT) == ticks


def test_a_gate_wider_than_a_dash_gap_stays_open() -> None:
    left = _dashes([(0, 0), (5, 0)])
    right = [[(x + 6.5, y) for x, y in c] for c in _dashes([(0, 0), (5, 0)])]
    pieces = [_piece(i, c) for i, c in enumerate([*left, *right])]
    out = chain_dashes(pieces, parent=PARENT)
    assert len(out) == 2
    assert out[0].geometry.bounds[2] < out[1].geometry.bounds[0]


def test_a_solid_polyline_exploded_into_segments_is_left_alone() -> None:
    pieces = [_piece(0, [(0, 0), (5, 0)]), _piece(1, [(5, 0), (5, 5)])]
    assert chain_dashes(pieces, parent=PARENT) == pieces


def test_dashes_of_other_layers_and_nested_blocks_do_not_join() -> None:
    a = _piece(0, [(0, 0), (0.75, 0)])
    b = _piece(1, [(1.25, 0), (2.0, 0)], layer="Граница площадки")
    nested = Feature(SourceRef("f", "c", f"{PARENT}~2~0"), CURB, LineString([(2.5, 0), (3.25, 0)]))
    assert chain_dashes([a, b, nested], parent=PARENT) == [a, b, nested]


def _write(path: Path, *, exploded: bool, linetype: str | None = None) -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.add(CURB)
    doc.layers.add("Навес", linetype="DASHED")
    msp = doc.modelspace()
    if exploded:
        block = doc.blocks.new("msdElementTypeLineString_7")
        for coords in _dashes([(0, 0), (12, 0), (12, 9)]):
            if len(coords) == 2:
                block.add_line(coords[0], coords[1])
            else:
                block.add_lwpolyline(coords)
        msp.add_blockref("msdElementTypeLineString_7", (100, 200), dxfattribs={"layer": CURB})
    attribs = {"layer": "Навес"} if linetype is None else {"layer": CURB, "linetype": linetype}
    msp.add_lwpolyline([(0, 50), (6, 50), (6, 56), (0, 56)], close=True, dxfattribs=attribs)
    doc.saveas(path)


def test_reader_restores_a_microstation_dashed_line(tmp_path: Path) -> None:
    source = tmp_path / "dashed.dxf"
    _write(source, exploded=True)
    scene = EzdxfSceneReader().read(source, unit="m")
    curbs = [f for f in scene.features if f.layer == CURB]
    assert len(curbs) == 1
    assert curbs[0].dashed
    assert curbs[0].geometry.distance(Point(112, 200)) < 1e-6
    # 21 м пути, последний штрих кончается на 20,75 м (шаг 1,25 м).
    assert curbs[0].geometry.length == pytest.approx(20.75, abs=0.02)
    # Учёт чтения: каждый штрих по-прежнему дал объект, исходов столько же, сколько посещений.
    assert sum(scene.read_diagnostics.outcomes.values()) == sum(
        scene.read_diagnostics.visited_by_type.values()
    )


@pytest.mark.parametrize(
    ("linetype", "dashed"), [(None, True), ("DASHED", True), ("CONTINUOUS", False)]
)
def test_dashed_linetype_marks_the_feature(
    tmp_path: Path, linetype: str | None, *, dashed: bool
) -> None:
    """Тип линии с разрывами из таблицы LTYPE - у сущности или по слою (BYLAYER)."""
    source = tmp_path / "linetype.dxf"
    _write(source, exploded=False, linetype=linetype)
    scene = EzdxfSceneReader().read(source, unit="m")
    assert [f.dashed for f in scene.features] == [dashed]


def test_dashes_written_out_of_order_still_join() -> None:
    """Харьковская: штрих, в который попала вершина, лист пишет двумя отрезками далеко от
    соседних штрихов. Подряд линия рвалась на куски с разрывом 1,7 м; концы сшиваются."""
    path = [(0, 0), (10.5, 0), (10.5, 8)]
    dashes = _dashes(path)
    corner = next(i for i, c in enumerate(dashes) if len(c) == 3)  # штрих с вершиной
    before, after = dashes[corner][:2], dashes[corner][1:]
    order = [*dashes[:corner], *dashes[corner + 1 :], before, after]
    pieces = [_piece(i, c) for i, c in enumerate(order)]
    out = chain_dashes(pieces, parent=PARENT)
    assert len(out) == 1
    assert (10.5, 0) in out[0].geometry.coords
    assert out[0].geometry.length == pytest.approx(LineString(path).length, abs=1.3)


def test_a_long_wall_is_not_a_dash_even_beside_a_gap() -> None:
    """Харьковская: стены школы - длинные отрезки, между двумя из них разрыв 0,5 м по прямой.
    Сшитые как штрихи, они получали признак пунктира и пропадали из объёмов."""
    walls = [_piece(0, [(0, 0), (11.4, 0)]), _piece(1, [(11.9, 0), (30, 0)])]
    assert chain_dashes(walls, parent=PARENT) == walls


def test_wall_pieces_with_one_doorway_gap_are_not_a_dashed_line() -> None:
    """Харьковская: у входа стена школы нарисована короткими кусками с одним разрывом. Один
    разрыв - проём или стык, а не пунктир: такая стена остаётся сплошной и даёт объём."""
    pieces = [_piece(0, [(0, 0), (1.5, 0)]), _piece(1, [(2.0, 0), (3.2, 0)])]
    assert chain_dashes(pieces, parent=PARENT) == pieces
