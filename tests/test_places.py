"""Место посадки: зонирование, полигоны проезжей части, «не определено»; категория В.6."""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, box
from test_quality import LAWN, LIME, _place

from green.application.places import Place, category_of, place_map, with_places
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Plan


def _f(geometry, cls: ObjectClass) -> Feature:  # noqa: ANN001 - фабрика теста
    return Feature(SourceRef("f", "x", str(id(geometry))), "слой", geometry, object_class=cls)


ROAD = _f(box(0.0, 0.0, 200.0, 10.0), ObjectClass.ROAD)
HOUSE = _f(box(40.0, 30.0, 80.0, 45.0), ObjectClass.BUILDING)


def test_no_data_no_place() -> None:
    places = place_map([HOUSE])
    assert places.source == "none"
    assert places.of(np.array([[10.0, 20.0]])) == [Place.UNKNOWN]
    assert category_of(Place.UNKNOWN, "streets") == "streets"


def test_carriageway_polygons_give_roadside_street_and_yard() -> None:
    places = place_map([ROAD, HOUSE])
    assert places.source == "road"
    xy = np.array([[10.0, 15.0], [10.0, 40.0], [60.0, 55.0]])
    assert places.of(xy) == [Place.ROADSIDE, Place.STREET, Place.YARD]
    assert category_of(Place.YARD, "streets") == "yards"
    assert category_of(Place.ROADSIDE, "yards") == "streets"


def test_building_outline_as_lines_hides_the_yard_too() -> None:
    walls = _f(LineString([(40, 30), (80, 30), (80, 45), (40, 45), (40, 30)]), ObjectClass.BUILDING)
    assert place_map([ROAD, walls]).of(np.array([[60.0, 55.0]])) == [Place.YARD]


def test_zoning_wins_over_the_road() -> None:
    yard = _f(box(0.0, 12.0, 30.0, 30.0), ObjectClass.TERRITORY_YARD)
    square = _f(box(100.0, 12.0, 150.0, 60.0), ObjectClass.TERRITORY_SQUARE)
    places = place_map([ROAD, HOUSE, yard, square])
    assert places.source == "zoning"
    xy = np.array([[10.0, 15.0], [120.0, 20.0], [180.0, 15.0]])
    assert places.of(xy) == [Place.YARD, Place.SQUARE, Place.ROADSIDE]


def test_with_places_fills_only_unplaced() -> None:
    plan = Plan(
        placements=(_place(1, 10.0, 15.0, LIME, note=LAWN), _place(2, 60.0, 55.0, LIME, note=LAWN)),
        rejections=(),
    )
    placed = with_places(plan, place_map([ROAD, HOUSE]))
    assert [p.place for p in placed.placements] == ["roadside", "yard"]
    again = with_places(placed, place_map([]))
    assert [p.place for p in again.placements] == ["roadside", "yard"]


def test_place_map_cache_is_per_drawing_and_forgotten_after_a_run() -> None:
    from green.application.constraints import forget_drawings
    from green.application.places import _LAST

    first = (ROAD, HOUSE)
    second = (HOUSE,)
    assert place_map(first).source == "road"
    assert place_map(second).source == "none"
    assert place_map(first).source == "road"
    forget_drawings()
    assert not _LAST
