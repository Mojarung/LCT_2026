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
from shapely.geometry import Polygon, box

from green.application.surfaces import build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.reports.artifacts import _round_turns, _surface

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
