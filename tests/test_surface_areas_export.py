"""Карта покрытий отдаёт и контуры: 3D-вид рисует проезды и газоны прямыми краями.

Растр карты покрытий - клетки 0,5-1 м: край асфальта на 3D-виде выходил лесенкой, «как будто
кто-то отгрыз» (пользователь, 17.10.2026). Контуры грунта и покрытия, из которых растр и
закрашен, теперь лежат в surface.json (areas): клиент рисует их поверх растра.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import shapely
from shapely.geometry import Point, Polygon, box

from green.application.basemap import Basemap, BasemapFeature, MaterialLabel
from green.application.surfaces import build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.reports.artifacts import _round_turns, _smoothed, _surface

if TYPE_CHECKING:
    from pathlib import Path

REF = SourceRef("f", "x", "1")
SITE = box(0, 0, 60, 40)
# Косой край проезда: в растре 1 м он лесенка, в контуре - одна прямая.
ROAD = Polygon([(0, 0), (60, 0), (60, 9), (0, 14)])
LAWN = Polygon([(0, 14), (60, 9), (60, 40), (0, 40)])


def _areas(tmp_path: Path) -> dict[str, list]:
    features = [
        Feature(REF, "ROAD", ROAD, object_class=ObjectClass.ROAD),
        Feature(REF, "LAWN", LAWN, object_class=ObjectClass.LAWN),
    ]
    surface = build_surface_map(features, [], SITE, 1.0)
    assert surface is not None
    _surface(tmp_path, surface)
    return json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]


def _union(polygons: list) -> shapely.Geometry:
    return shapely.union_all([Polygon(rings[0], rings[1:]) for rings in polygons])


def test_surface_json_carries_soil_and_paved_contours(tmp_path: Path) -> None:
    areas = _areas(tmp_path)
    paved, soil = _union(areas["paved"]), _union(areas["soil"])
    assert paved.symmetric_difference(ROAD).area < 0.5
    assert soil.symmetric_difference(LAWN).area < 0.5
    assert paved.intersection(soil).area < 0.01


def test_slanted_edge_stays_one_straight_line(tmp_path: Path) -> None:
    paved = _union(_areas(tmp_path)["paved"])
    edge = paved.boundary.intersection(box(1, 8.5, 59, 14.5))
    # Лесенка растра дала бы десятки вершин, контур - одну прямую от (0, 14) до (60, 9).
    assert len(shapely.get_coordinates(edge)) <= 4


def test_raster_only_material_gets_straight_contours(tmp_path: Path) -> None:
    """Грунт и покрытие, выведенные разливом от подписей, есть только в растре: их край на 3D
    был лесенкой с выгрызами. Растр переводится в контуры и выпрямляется с допуском в клетку."""
    features = [
        Feature(REF, "ROAD", ROAD, object_class=ObjectClass.ROAD),
        Feature(REF, "LAWN", LAWN, object_class=ObjectClass.LAWN),
    ]
    exact = build_surface_map(features, [], SITE, 0.5)
    assert exact is not None
    raster_only = replace(exact, soil_area=None, paved_area=None)
    _surface(tmp_path, raster_only)
    areas = json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]
    paved = _union(areas["paved"])
    assert paved.symmetric_difference(ROAD).area < 0.03 * ROAD.area
    edge = paved.boundary.intersection(box(2, 8.5, 58, 14.5))
    assert len(shapely.get_coordinates(edge)) <= 6


def test_turns_are_rounded_and_right_angles_stay() -> None:
    """Пользователь 17.10.2026: «где поворот - закругление». Поворот дороги (излом меньше 75°)
    скругляется срезом угла, прямой угол здания или площадки остаётся углом."""
    square = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0), (0.0, 0.0)]
    assert _round_turns(square) == square
    # Поворот дороги на 90° двумя изломами по 45°.
    bend = [(0.0, 0.0), (20.0, 0.0), (26.0, 6.0), (26.0, 26.0), (0.0, 26.0), (0.0, 0.0)]
    rounded = _round_turns(bend)
    assert (20.0, 0.0) not in rounded
    assert (26.0, 6.0) not in rounded
    assert (26.0, 26.0) in rounded  # прямой угол
    assert Polygon(rounded).is_valid
    assert abs(Polygon(rounded).area - Polygon(bend).area) < 0.05 * Polygon(bend).area


def _kinds(tmp_path: Path, features: list[Feature], labels: list, basemap_features: list) -> dict:
    surface = build_surface_map(features, [], SITE, 0.5)
    assert surface is not None
    basemap = Basemap(
        features=tuple(basemap_features),
        features_in=len(basemap_features),
        features_out=len(basemap_features),
        dropped={},
        bbox=SITE.bounds,
        labels=tuple(labels),
    )
    _surface(tmp_path, replace(surface, paved_area=None, soil_area=None), basemap)
    areas = json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]
    return {
        kind: _union(
            [p for p, k in zip(areas["paved"], areas["paved_kind"], strict=True) if k == kind]
        )
        for kind in ("road", "asphalt", "pavers", "paved")
    } | {"road_mesh": _union(areas["road_mesh"]) if areas["road_mesh"] else None}


def test_paved_parts_are_road_sidewalk_or_tiles(tmp_path: Path) -> None:
    """Пользователь 17.10.2026: асфальт проезда и тротуар различаются не шириной, а чертежом.
    Подпись съёмки «ПЛ» - плитка, «А» - асфальт; полоса шире 3,5 м без плитки - проезжая часть
    (опускается на высоту борта), уже - тротуар."""
    strips = {
        "tiles": box(0, 30, 60, 38),  # 8 м, подпись ПЛ - плиточная площадка, не проезд
        "road": box(0, 0, 60, 8),  # 8 м без подписи - проезд
        "walk": box(0, 10, 60, 12),  # 2 м с подписью А - асфальтовый тротуар
        "path": box(0, 20, 60, 21.5),  # 1,5 м без подписи - покрытие неизвестно
    }
    features = [
        Feature(REF, name, g, object_class=ObjectClass.SIDEWALK) for name, g in strips.items()
    ]
    labels = [
        MaterialLabel(30, 34, "ПЛ", "paved"),
        MaterialLabel(30, 11, "А", "paved"),
    ]
    kinds = _kinds(tmp_path, features, labels, [])
    assert kinds["pavers"].intersection(strips["tiles"]).area > 0.9 * strips["tiles"].area
    assert kinds["road"].intersection(strips["road"]).area > 0.9 * strips["road"].area
    assert kinds["asphalt"].intersection(strips["walk"]).area > 0.8 * strips["walk"].area
    assert kinds["paved"].intersection(strips["path"]).area > 0.8 * strips["path"].area
    assert kinds["road"].intersection(strips["walk"]).area < 0.01
    # Проезжая часть приходит и сеткой для 3D с запасом под край тротуара.
    assert kinds["road_mesh"].contains(strips["road"].buffer(0.2))


def test_drawn_road_polygon_beats_width(tmp_path: Path) -> None:
    """Проезжая часть чертежа (класс road) - проезд даже узкой полосой, тротуар чертежа - нет."""
    lane = box(0, 0, 60, 3)
    wide_walk = box(0, 10, 60, 16)
    features = [
        Feature(REF, "lane", lane, object_class=ObjectClass.ROAD),
        Feature(REF, "walk", wide_walk, object_class=ObjectClass.SIDEWALK),
    ]
    basemap = [
        BasemapFeature(ObjectClass.ROAD, lane),
        BasemapFeature(ObjectClass.SIDEWALK, wide_walk),
    ]
    kinds = _kinds(tmp_path, features, [], basemap)
    assert kinds["road"].intersection(lane).area > 0.9 * lane.area
    assert kinds["road"].intersection(wide_walk).area < 0.01


def test_paved_spikes_and_notches_are_smoothed(tmp_path: Path) -> None:
    """Зубец и выемка шириной в полметра на краю проезда (лесенка разлива) давали на 3D рваный борт:
    у частей покрытия снимаются выступы и выемки уже метра."""
    road = box(0, 0, 60, 10).union(box(30, 10, 30.5, 11.5)).difference(box(40, 9, 40.5, 10))
    features = [Feature(REF, "road", road, object_class=ObjectClass.ROAD)]
    basemap = [BasemapFeature(ObjectClass.ROAD, road)]
    kinds = _kinds(tmp_path, features, [], basemap)
    smooth = kinds["road"]
    assert not smooth.intersects(box(30.1, 10.6, 30.4, 11.4))  # зубец снят
    assert smooth.contains(box(40.1, 9.1, 40.4, 9.9))  # выемка закрыта
    assert smooth.contains(box(1, 1, 59, 9))


def test_sawtooth_wall_of_a_bite_becomes_one_edge() -> None:
    """Стенка выемки проезда пилой с зубцами 0,5-0,75 м (Камчатская, 17.10.2026): борт по ней
    шёл крест-накрест «палочками». Зубцы снимаются, выемка остаётся пустой."""
    road = Polygon(
        [
            (180, -83.83),
            (193.25, -83.83),
            (192.75, -82.83),
            (193.5, -82.83),
            (193.09, -82.0),
            (195.75, -82.0),
            (195.75, -83.83),
            (205, -83.83),
            (205, -78),
            (180, -78),
        ]
    )
    smooth = _smoothed(road)
    teeth = box(192.6, -83.7, 193.6, -82.1)
    inside = [p for p in shapely.get_coordinates(smooth.boundary) if teeth.contains(Point(p))]
    assert inside == []
    assert not smooth.intersects(box(194, -83.7, 195.5, -82.2))
    assert smooth.contains(box(181, -83.5, 192, -78.5))
    assert smooth.contains(box(197, -83.5, 204, -78.5))


def test_smoothing_does_not_glue_parts_across_a_curb_seam(tmp_path: Path) -> None:
    """Плиточная площадка в полуметре от проезда (щель - линия борта) остаётся плиткой."""
    road, tiles = box(0, 0, 60, 8), box(20, 8.5, 26, 14)
    features = [
        Feature(REF, "road", road, object_class=ObjectClass.SIDEWALK),
        Feature(REF, "tiles", tiles, object_class=ObjectClass.SIDEWALK),
    ]
    kinds = _kinds(tmp_path, features, [MaterialLabel(23, 11, "ПЛ", "paved")], [])
    assert kinds["pavers"].intersection(tiles).area > 0.8 * tiles.area
    assert kinds["road"].intersection(tiles).area < 0.01
    assert kinds["road"].intersection(road).area > 0.9 * road.area
