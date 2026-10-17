"""Школы и детские сады: здание чертежа, совпавшее с контуром OSM, получает отступ 10 м.

743-ПП, табл. 3.6.1: «Наружная стена школьного здания или здания детского сада 10,0 1,5».
Назначения здания в топоплане нет (docs/notes/21), контуры - выгрузка OpenStreetMap
(config/gis/osm_schools_moscow.geojson). Школой становится только здание самого чертежа,
совпавшее с контуром OSM: сдвиг или чужая система координат не создают школ на пустом месте.
"""

from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, box

from green.application.schools import mark_schools
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.config.repositories import YamlRuleBookSource

ROOT = Path(__file__).resolve().parents[1]


def _f(cls: ObjectClass, geometry: object, handle: str = "1") -> Feature:
    return Feature(SourceRef("f", "x", handle), "Здания", geometry, object_class=cls)  # type: ignore[arg-type]


def test_building_polygon_matching_an_osm_school_becomes_a_school() -> None:
    house = _f(ObjectClass.BUILDING, box(0, 0, 40, 20), "h1")
    other = _f(ObjectClass.BUILDING, box(100, 0, 140, 20), "h2")
    osm = [_f(ObjectClass.SCHOOL, box(1, 1, 41, 21), "osm")]
    features, note = mark_schools([house, other], osm)
    schools = [f for f in features if f.object_class is ObjectClass.SCHOOL]
    assert len(schools) == 1
    assert schools[0].ref == house.ref
    assert schools[0].geometry.equals(house.geometry)
    assert len(features) == 3  # здание остаётся зданием, школа - дополнительный объект
    assert "1 здан" in note
    assert "743-ПП" in note


def test_building_drawn_as_wall_lines_is_matched_by_perimeter() -> None:
    walls = [
        _f(ObjectClass.BUILDING, LineString([(0, 0), (40, 0), (40, 20)]), "w1"),
        _f(ObjectClass.BUILDING, LineString([(40, 20), (0, 20), (0, 0)]), "w2"),
    ]
    osm = [_f(ObjectClass.SCHOOL, box(0.5, 0.5, 40.5, 20.5), "osm")]
    features, _ = mark_schools(walls, osm)
    assert sum(f.object_class is ObjectClass.SCHOOL for f in features) == 2


def test_osm_school_without_a_drawn_building_adds_nothing() -> None:
    house = _f(ObjectClass.BUILDING, box(0, 0, 40, 20))
    osm = [_f(ObjectClass.SCHOOL, box(500, 500, 540, 520), "osm")]
    features, note = mark_schools([house], osm)
    assert features == (house,)
    assert note == ""


def test_school_rules_are_ten_and_one_and_a_half_metres() -> None:
    book = YamlRuleBookSource(ROOT / "config/acts.yaml", ROOT / "config/rules.yaml").load()
    rules = {
        r.planting_type.value: r
        for r in book.distance_rules
        if r.object_class is ObjectClass.SCHOOL
    }
    assert rules["tree"].min_distance_m == 10.0
    assert rules["shrub"].min_distance_m == 1.5
    assert "3.6.1" in rules["tree"].citation.clause
