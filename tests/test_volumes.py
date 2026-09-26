"""Объёмы зданий для трёхмерной сцены: грани из линий, дворы и высота по подписям.

Главные проверки - что двор не становится зданием, номер дома не становится этажностью, и
что баланс граней сходится: каждая замкнутая грань либо объём, либо двор, либо обломок, а у
каждой высоты одно основание.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from shapely.geometry import LineString, Point, Polygon, box

from green.application.volumes import (
    CONTAINER_M,
    PORCH_M,
    STRUCTURE_M,
    build_volumes,
    normalize_label,
    storey_height,
)
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from green.application.volumes import BuildingVolume, Volumes

HOUSE = "output[1-12]_3_ДЖКХ-24_03233tp$0$Здания"
PART = "output[1-12]_3_ДЖКХ-24_03233tp$0$Части зданий"
NUMBER = "output[1-12]_3_ДЖКХ-24_03233tp$0$Номер дома"
LAWN = "output[1-12]_3_ДЖКХ-24_03233tp$0$Леса и газоны"
EM_DASH = "—"


def _ref(handle: str) -> SourceRef:
    return SourceRef(file_sha8="aaaaaaaa", xref_hash8="00000000", handle=handle)


def _feature(
    geometry: BaseGeometry, layer: str = HOUSE, cls: ObjectClass = ObjectClass.BUILDING
) -> Feature:
    return Feature(ref=_ref(layer[-6:]), layer=layer, geometry=geometry, object_class=cls)


def _label(x: float, y: float, text: str, layer: str = HOUSE) -> TextLabel:
    return TextLabel(ref=_ref(text), layer=layer, x=x, y=y, text=text)


def _balanced(volumes: Volumes) -> Volumes:
    """Баланс граней обязан сходиться в каждом тесте, а не только в отдельном."""
    assert volumes.faces == len(volumes.buildings) + volumes.voids + volumes.slivers
    sources = volumes.from_labels + volumes.from_neighbors + volumes.from_letters
    assert len(volumes.buildings) == sources + volumes.assumed
    return volumes


def _at(volumes: Volumes, x: float, y: float) -> BuildingVolume:
    found = [b for b in volumes.buildings if b.footprint.contains(Point(x, y))]
    assert len(found) == 1, f"в точке ({x}, {y}) объёмов {len(found)}"
    return found[0]


def test_numeric_label_inside_a_closed_outline_gives_the_floors() -> None:
    volumes = _balanced(
        build_volumes(
            [_feature(box(0, 0, 20, 10))],
            [_label(5, 5, "К" + EM_DASH), _label(8, 5, "9"), _label(8, 3, "Ж")],
        )
    )

    (house,) = volumes.buildings
    assert house.floors == 9
    assert house.floors_source == "label"
    assert house.height_m == pytest.approx(3.0 * 9 + 1.2)
    assert (house.kind, house.wall, house.use) == ("building", "brick", "residential")
    assert house.labels == ("К-", "9", "Ж")
    assert volumes.from_labels == 1


def test_open_lines_with_a_gap_under_two_centimetres_close_into_one_face() -> None:
    """Контур из двух кусков, как на стыке планшетов: концы разошлись на полтора сантиметра."""
    first = LineString([(0, 0), (10, 0), (10, 10)])
    second = LineString([(10.012, 10.008), (0, 10), (0, 0.015)])

    volumes = _balanced(build_volumes([_feature(first), _feature(second)], [_label(5, 5, "3")]))

    assert volumes.faces == 1
    assert volumes.open_lines == 0
    (house,) = volumes.buildings
    assert house.footprint.area == pytest.approx(100, abs=0.5)
    assert house.floors == 3


def test_a_real_gap_does_not_close_and_the_lines_are_counted() -> None:
    # Вдали от рамок планшетов (сетка 250 м): в узле сетки разрыв закрыла бы рамка.
    first = LineString([(100, 100), (110, 100), (110, 110)])
    second = LineString([(110.5, 110), (100, 110), (100, 100.5)])

    volumes = _balanced(build_volumes([_feature(first), _feature(second)], []))

    assert volumes.buildings == ()
    assert volumes.faces == 0
    assert volumes.open_lines == 2


def test_a_wall_ending_short_of_another_wall_still_splits_the_building() -> None:
    """Т-стык: внутренняя стена не дошла до наружной на сантиметр."""
    outline = LineString([(0, 0), (20, 0), (20, 10), (0, 10), (0, 0)])
    inner = LineString([(10, 0.01), (10, 9.99)])

    volumes = _balanced(build_volumes([_feature(outline), _feature(inner)], []))

    assert len(volumes.buildings) == 2
    assert volumes.open_lines == 0


def test_the_courtyard_of_a_ring_building_is_a_void_and_not_extruded() -> None:
    ring = Polygon(
        [(0, 0), (40, 0), (40, 40), (0, 40)], holes=[[(10, 10), (30, 10), (30, 30), (10, 30)]]
    )

    volumes = _balanced(build_volumes([_feature(ring)], [_label(5, 20, "6")]))

    assert volumes.voids == 1
    (house,) = volumes.buildings
    assert house.floors == 6
    assert len(house.footprint.interiors) == 1
    assert not any(b.footprint.contains(Point(20, 20)) for b in volumes.buildings)


def test_a_kiosk_in_the_courtyard_is_not_mistaken_for_the_courtyard() -> None:
    """Киоск в дыре полигона не касается края двора: он здание, а двор - пустота."""
    ring = Polygon(
        [(0, 0), (40, 0), (40, 40), (0, 40)], holes=[[(10, 10), (30, 10), (30, 30), (10, 30)]]
    )

    volumes = _balanced(build_volumes([_feature(ring), _feature(box(18, 18, 22, 22))], []))

    assert volumes.voids == 1
    kiosk = _at(volumes, 20, 20)
    assert kiosk.floors_source == "assumed"
    assert kiosk.floors == 1


def test_a_lawn_inside_an_enclosed_face_makes_it_a_courtyard() -> None:
    """Двор, обведённый стенами из линий: дыры полигона нет, есть газон внутри."""
    walls = LineString([(0, 0), (30, 0), (30, 30), (0, 30), (0, 0)])
    lawn = _feature(box(5, 5, 25, 25), LAWN, ObjectClass.LAWN)

    with_lawn = _balanced(build_volumes([_feature(walls), lawn], []))
    without = _balanced(build_volumes([_feature(walls)], []))

    assert with_lawn.buildings == ()
    assert with_lawn.voids == 1
    assert len(without.buildings) == 1


def test_a_soil_label_from_another_layer_makes_it_a_courtyard() -> None:
    walls = LineString([(0, 0), (30, 0), (30, 30), (0, 30), (0, 0)])

    volumes = _balanced(build_volumes([_feature(walls)], [_label(15, 15, "ГАЗОН", LAWN)]))

    assert volumes.buildings == ()
    assert volumes.voids == 1


def test_a_lawn_line_along_the_wall_does_not_make_the_house_a_courtyard() -> None:
    walls = LineString([(0, 0), (30, 0), (30, 30), (0, 30), (0, 0)])
    edge = _feature(LineString([(0, 0), (30, 0)]), LAWN, ObjectClass.LAWN)

    volumes = _balanced(build_volumes([_feature(walls), edge], []))

    assert len(volumes.buildings) == 1


def test_a_building_label_wins_over_open_ground_evidence() -> None:
    walls = LineString([(0, 0), (30, 0), (30, 30), (0, 30), (0, 0)])
    tree = _feature(Point(15, 15), LAWN, ObjectClass.EXISTING_TREE)

    volumes = _balanced(build_volumes([_feature(walls), tree], [_label(5, 5, "2")]))

    assert volumes.buildings[0].floors == 2


def test_house_number_layer_text_is_not_read_as_floors() -> None:
    house = _feature(box(0, 0, 10, 10))

    volumes = _balanced(build_volumes([house], [_label(5, 5, "12", NUMBER)]))

    (volume,) = volumes.buildings
    assert volume.floors_source == "assumed"
    assert volume.floors == 1
    assert volume.labels == ()


def test_an_unlabeled_part_inherits_floors_from_the_labeled_neighbor() -> None:
    """Корпус из частей: подписана одна, соседняя с общей стеной 10 м берёт её этажность."""
    tower = _feature(box(0, 0, 10, 10))
    wing = _feature(box(10, 0, 30, 10), PART)
    corner = _feature(box(-5, 10, 0, 15), PART)  # касается башни только углом

    volumes = _balanced(build_volumes([tower, wing, corner], [_label(5, 5, "16")]))

    assert _at(volumes, 5, 5).floors_source == "label"
    inherited = _at(volumes, 20, 5)
    assert (inherited.floors, inherited.floors_source) == (16, "neighbor")
    assert _at(volumes, -2.5, 12.5).floors_source == "assumed"
    assert volumes.from_neighbors == 1


def test_porch_letters_alone_make_a_porch_and_mya_a_container_site() -> None:
    house = _feature(box(0, 0, 20, 10))
    porch = _feature(box(5, -2, 8, 0), PART)
    bins = _feature(box(30, 0, 32, 2))

    volumes = _balanced(
        build_volumes(
            [house, porch, bins],
            [_label(5, 5, "5"), _label(6, -1, "А", PART), _label(31, 1, "М.Я.")],
        )
    )

    stoop = _at(volumes, 6.5, -1)
    assert (stoop.kind, stoop.floors, stoop.height_m) == ("porch", None, PORCH_M)
    assert stoop.floors_source == "letter"
    site = _at(volumes, 31, 1)
    assert (site.kind, site.height_m) == ("container", CONTAINER_M)
    assert _at(volumes, 10, 5).floors == 5


def test_letters_without_a_number_give_assumed_floors() -> None:
    flats = _feature(box(0, 0, 20, 10))
    shop = _feature(box(100, 0, 120, 10))

    volumes = _balanced(build_volumes([flats, shop], [_label(5, 5, "Ж"), _label(105, 5, "Н")]))

    assert (_at(volumes, 5, 5).floors, _at(volumes, 5, 5).floors_source) == (5, "letter")
    assert (_at(volumes, 105, 5).floors, _at(volumes, 105, 5).use) == (1, "non_residential")
    assert volumes.from_letters == 2


@pytest.mark.parametrize(
    ("side", "floors"),
    [(10.0, 1), (20.0, 2), (30.0, 5)],
)
def test_without_any_label_floors_follow_the_footprint_area(side: float, floors: int) -> None:
    volumes = _balanced(build_volumes([_feature(box(0, 0, side, side))], []))

    (volume,) = volumes.buildings
    assert (volume.floors, volume.floors_source) == (floors, "assumed")
    assert volume.height_m == storey_height(floors)


def test_a_huge_unlabeled_face_is_a_void_not_a_building() -> None:
    volumes = _balanced(build_volumes([_feature(box(0, 0, 60, 60))], []))

    assert volumes.buildings == ()
    assert volumes.voids == 1


def test_a_label_anchored_just_outside_a_small_building_still_belongs_to_it() -> None:
    """Точка вставки текста - левый нижний угол: у киоска она выходит за контур."""
    volumes = _balanced(build_volumes([_feature(box(0, 0, 3, 2))], [_label(1.5, -0.3, "2")]))

    assert volumes.buildings[0].floors == 2


def test_structures_get_a_fixed_height_and_open_structure_lines_are_counted() -> None:
    vent = _feature(box(0, 0, 3, 3), "tp$0$Вентиляторы", ObjectClass.STRUCTURE)
    parapet = _feature(LineString([(10, 0), (20, 0)]), "tp$0$Парапеты", ObjectClass.STRUCTURE)

    volumes = _balanced(build_volumes([vent, parapet], []))

    (volume,) = volumes.buildings
    assert (volume.kind, volume.height_m, volume.floors) == ("structure", STRUCTURE_M, None)
    assert volumes.open_lines == 1


def test_empty_geometry_and_points_on_building_layers_are_ignored() -> None:
    """Пустая линия последней в наборе не должна сбить сшивку концов остальных линий."""
    first = LineString([(0, 0), (10, 0), (10, 10)])
    second = LineString([(10.012, 10.008), (0, 10), (0, 0.015)])
    stray = [_feature(Point(50, 50)), _feature(LineString())]

    volumes = _balanced(build_volumes([_feature(first), _feature(second), *stray], []))

    assert len(volumes.buildings) == 1
    assert volumes.open_lines == 0


def test_specks_are_dropped_and_counted() -> None:
    column = _feature(Point(0, 0).buffer(0.2))

    volumes = _balanced(build_volumes([column], []))

    assert volumes.buildings == ()
    assert volumes.slivers == 1


@pytest.mark.parametrize(
    ("raw", "normal"),
    [("К—", "К-"), ("СМ–", "СМ-"), (" K- ", "К-"), ("м. я.", "М.Я.")],
)
def test_labels_are_normalized_before_reading(raw: str, normal: str) -> None:
    assert normalize_label(raw) == normal


def test_one_storey_is_taller_than_a_residential_storey() -> None:
    assert storey_height(1) == pytest.approx(4.0)
    assert storey_height(5) == pytest.approx(16.2)


def test_a_house_cut_by_the_sheet_frame_closes_along_the_frame() -> None:
    """Контур дома оборван рамкой планшета x = 16000: основание кончается на рамке."""
    cut = LineString([(16000, -5010), (15980, -5010), (15980, -5030), (16000, -5030)])

    volumes = _balanced(build_volumes([_feature(cut)], [_label(15990, -5020, "9")]))

    (house,) = volumes.buildings
    assert house.footprint.area == pytest.approx(400, abs=0.5)
    assert house.floors == 9
    assert volumes.closed_cuts == 1
    assert volumes.open_lines == 0


def test_a_house_cut_into_two_sheets_closes_on_both_sides() -> None:
    """Куски одного дома по обе стороны рамки y = -5250 разошлись на полметра: оба замкнуты."""
    north = LineString([(16100, -5250), (16100, -5240), (16140, -5240), (16140, -5250)])
    south = LineString([(16100.5, -5250), (16100.5, -5262), (16140, -5262), (16140, -5250)])

    volumes = _balanced(
        build_volumes([_feature(north), _feature(south)], [_label(16120, -5245, "12")])
    )

    assert len(volumes.buildings) == 2
    assert {b.floors for b in volumes.buildings} == {12}
    assert {b.floors_source for b in volumes.buildings} == {"label", "neighbor"}


def test_a_chain_around_three_sides_closes_with_a_chord_but_a_wall_does_not() -> None:
    three_sides = LineString([(120, 100), (100, 100), (100, 115), (120, 115)])
    wall = LineString([(200, 100), (230, 100)])

    volumes = _balanced(build_volumes([_feature(three_sides), _feature(wall)], []))

    (house,) = volumes.buildings
    assert house.footprint.area == pytest.approx(300, abs=0.5)
    assert volumes.closed_cuts == 1
    assert volumes.open_lines == 1


def test_dashes_of_building_parts_are_not_closed_into_canopies() -> None:
    """Пунктир выступов (штрихи по полметра) остаётся пунктиром, а не объёмом до земли."""
    dashes = [
        _feature(LineString([(100 + i, 100), (100 + i + 0.5, 100)]), layer=PART) for i in range(10)
    ]
    dashes += [
        _feature(LineString([(110, 100 + i), (110, 100 + i + 0.5)]), layer=PART) for i in range(10)
    ]

    volumes = _balanced(build_volumes(dashes, []))

    assert volumes.buildings == ()
    assert volumes.closed_cuts == 0
