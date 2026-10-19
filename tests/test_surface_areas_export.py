"""Карта покрытий отдаёт и контуры: 3D-вид рисует проезды и газоны прямыми краями.

Растр карты покрытий - клетки 0,5-1 м: край асфальта на 3D-виде выходил лесенкой, «как будто
кто-то отгрыз» (пользователь, 17.10.2026). Контуры грунта и покрытия, из которых растр и
закрашен, теперь лежат в surface.json (areas): клиент рисует их поверх растра.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box

from green.application.basemap import Basemap, BasemapFeature, MaterialLabel
from green.application.constraints import work_boundary
from green.application.surfaces import (
    DISPLAY_MARGIN_M,
    Material,
    build_surface_map,
    display_extent,
)
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel
from green.infrastructure.reports.artifacts import (
    SUBDIVIDE_VERTICES,
    _drawn_beds,
    _export_parts,
    _lawn_islands,
    _overlap_areas,
    _polygon_rings,
    _round_turns,
    _smoothed,
    _subdivided,
    _surface,
    _tidy,
    _walk_ends_to_road,
    _walk_notches_paved,
    _without_artifact_holes,
)

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
        for kind in ("road", "asphalt", "pavers", "paved", "special")
    } | {"road_mesh": _union(areas["road_mesh"]) if areas["road_mesh"] else None}


def test_paved_parts_are_road_sidewalk_or_tiles(tmp_path: Path) -> None:
    """Пользователь 17.10.2026: асфальт проезда и тротуар различаются не шириной, а чертежом.
    Подпись съёмки «ПЛ» - плитка, «А» - асфальт; полоса шире 3,5 м без плитки - проезжая часть
    (опускается на высоту борта), уже - тротуар."""
    strips = {
        "tiles": box(0, 30, 60, 38),  # 8 м, подпись ПЛ - плиточная площадка, не проезд
        "road": box(0, 0, 60, 8),  # 8 м без подписи - проезд
        "walk": box(0, 10, 60, 12),  # 2 м с подписью А - асфальтовый тротуар
        "path": box(0, 20, 60, 21.5),  # 1,5 м без подписи - асфальт
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
    # Узкая полоса без подписи - асфальт целиком: плитку съёмка подписывает, а раньше 3D
    # делил полосу по ширине попиксельно, и граница плитки и асфальта шла пятнами.
    assert kinds["asphalt"].intersection(strips["path"]).area > 0.8 * strips["path"].area
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


def test_smoothing_survives_a_mitre_closing_that_crosses_itself() -> None:
    """Олимпийская деревня, 18.10.2026: замыкание выемок с прямыми углами дало у кромки
    тротуара самопересечение, и пересечение GEOS роняло весь прогон (TopologyException)."""
    data = Path(__file__).parent / "data" / "paved_mitre_self_intersection.wkt"
    area = shapely.from_wkt(data.read_text(encoding="utf-8"))
    smooth = _smoothed(area)
    assert smooth.is_valid
    assert smooth.area > 0.9 * area.area


def test_raster_material_stops_at_the_fence(tmp_path: Path) -> None:
    """Харьковская у дома 1А (пользователь, 18.10.2026): плитка площадки из разлива подписи
    перелезала за ограду каплей. Грань, замкнутая оградой, целиком того материала, которого
    в ней больше; за оградой - газон."""
    playground = box(20, 15, 40, 30)
    spilled = box(18.5, 13.5, 41.5, 31.5)  # разлив вышел за ограду на 1,5 м
    features = [
        Feature(REF, "LAWN", SITE, object_class=ObjectClass.LAWN),
        Feature(REF, "WALK", spilled, object_class=ObjectClass.SIDEWALK),
    ]
    surface = build_surface_map(features, [], SITE, 0.5)
    assert surface is not None
    basemap = Basemap(
        features=(BasemapFeature(ObjectClass.FENCE, playground.exterior),),
        features_in=1,
        features_out=1,
        dropped={},
        bbox=SITE.bounds,
    )
    _surface(tmp_path, replace(surface, paved_area=None, soil_area=None), basemap)
    areas = json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]
    paved, soil = _union(areas["paved"]), _union(areas["soil"])

    assert paved.symmetric_difference(playground).area < 0.05 * playground.area
    assert soil.intersection(playground).area < 1.0
    assert soil.contains(Point(19.2, 22))  # полоса между оградой и краем разлива - газон


def test_playground_special_cover_is_its_own_kind(tmp_path: Path) -> None:
    """Детская площадка «СПЕЦ.ПОКР.» (Харьковская, 54 подписи): резиновое покрытие, а не
    плитка (пользователь, 19.10.2026, панорама площадки у дома 1А)."""
    walk, ground = box(0, 0, 60, 3), box(20, 6, 34, 20)
    features = [
        Feature(REF, "walk", walk, object_class=ObjectClass.SIDEWALK),
        Feature(REF, "ground", ground, object_class=ObjectClass.SIDEWALK),
    ]
    labels = [
        MaterialLabel(27, 13, "СПЕЦ.ПОКР.", "paved"),
        MaterialLabel(10, 1.5, "А", "paved"),
    ]
    kinds = _kinds(tmp_path, features, labels, [])
    assert kinds["special"].intersection(ground).area > 0.9 * ground.area
    assert kinds["special"].intersection(walk).area < 0.01


def test_asphalt_walk_by_the_curb_stays_asphalt(tmp_path: Path) -> None:
    """Пользователь 19.10.2026: тротуар у борта Харьковской на панораме - асфальт, а 3D делал
    его плиткой («пофикси везде траблы с асфальтом»). Подпись «А» решает за всю часть: и у
    борта, и вдали от проезда - асфальт, без смены материала по длине; стоянка - не плитка."""
    strips = {
        "road": box(0, 0, 60, 8),
        "walk": box(0, 8.5, 30, 11.5),  # 3 м за бортом, подпись А
        "parking": box(32, 8.5, 60, 20.5),  # 12 м за бортом, подпись А
        "path": box(0, 25, 30, 27),  # 2 м вдали от проезда, подпись А
    }
    features = [
        Feature(REF, name, g, object_class=ObjectClass.SIDEWALK) for name, g in strips.items()
    ]
    labels = [
        MaterialLabel(15, 10, "А", "paved"),
        MaterialLabel(45, 14, "А", "paved"),
        MaterialLabel(15, 26, "А", "paved"),
    ]
    kinds = _kinds(tmp_path, features, labels, [])
    for name in ("walk", "path"):
        assert kinds["asphalt"].intersection(strips[name]).area > 0.8 * strips[name].area
    for name in ("walk", "parking", "path"):
        assert kinds["pavers"].intersection(strips[name]).area < 0.01


def test_playground_wins_a_tie_with_asphalt_labels(tmp_path: Path) -> None:
    """Площадка у дома 1А: «ДЕТ.ПЛ.», «СПЕЦ.ПОКРЫТИЕ» и две «А» дорожек в одной части -
    при равенстве голосов это площадка (подпись площадки прямо о ней, «А» - о соседях)."""
    ground = box(20, 6, 34, 20)
    features = [Feature(REF, "ground", ground, object_class=ObjectClass.SIDEWALK)]
    labels = [
        MaterialLabel(27, 13, "ДЕТ.ПЛ.", "paved"),
        MaterialLabel(27, 11, "СПЕЦ.ПОКРЫТИЕ", "paved"),
        MaterialLabel(21, 7, "А", "paved"),
        MaterialLabel(33, 19, "А", "paved"),
    ]
    kinds = _kinds(tmp_path, features, labels, [])
    assert kinds["special"].intersection(ground).area > 0.9 * ground.area


def test_path_through_the_playground_gate_is_not_rubber(tmp_path: Path) -> None:
    """Дорожка 2 м, вошедшая в площадку через калитку, - одна часть покрытия с площадкой;
    резина - только тело площадки, дорожка остаётся дорожкой."""
    ground, path = box(20, 6, 34, 20), box(26, 20, 28, 34)
    features = [
        Feature(REF, "ground", ground, object_class=ObjectClass.SIDEWALK),
        Feature(REF, "path", path, object_class=ObjectClass.SIDEWALK),
    ]
    labels = [
        MaterialLabel(27, 13, "ДЕТ.ПЛ.", "paved"),
        MaterialLabel(27, 11, "СПЕЦ.ПОКРЫТИЕ", "paved"),
        MaterialLabel(27, 30, "А", "paved"),
    ]
    kinds = _kinds(tmp_path, features, labels, [])
    assert kinds["special"].intersection(ground).area > 0.9 * ground.area
    assert kinds["special"].intersection(box(26, 22, 28, 34)).area < 0.05 * 24
    outside = box(26, 22, 28, 34)
    assert (kinds["pavers"] | kinds["asphalt"]).intersection(outside).area > 0.8 * outside.area


def test_lawn_edge_loses_sawtooth_and_slivers() -> None:
    """Харьковская, 19.10.2026: газон минус покрытие, чьи края разошлись на сантиметры, -
    зубцы через полметра (36 713 вершин, 10 209 смен поворота) и щепки; в 3D край газона шёл
    волной. Пила и щепки снимаются, полоса газона 1 м у борта остаётся."""
    teeth = [(x * 0.5, 10.0 + (0.08 if x % 2 else 0.0)) for x in range(41)]
    lawn = Polygon([(0.0, 0.0), (20.0, 0.0), *reversed(teeth)])
    sliver = box(20.0, 0.0, 30.0, 0.1)
    strip = box(0.0, 20.0, 20.0, 21.0)
    tidy = _tidy(shapely.union_all([lawn, sliver, strip]))
    assert tidy is not None
    assert not tidy.intersects(box(21.0, 0.0, 30.0, 0.1))
    assert tidy.contains(box(1.0, 20.2, 19.0, 20.8))
    edge = tidy.boundary.intersection(box(1.0, 9.0, 19.0, 11.0))
    assert len(shapely.get_coordinates(edge)) <= 4


def test_playground_inside_a_big_paved_network_gets_rubber(tmp_path: Path) -> None:
    """Харьковская: площадка, соединённая дорожками с большой сетью тротуаров, - одна часть
    покрытия с десятком «А»; голосованием она проигрывала и шла плиткой. Тело площадки с её
    подписью - резина, сеть остаётся тротуаром."""
    ground = box(20, 6, 34, 20)
    walk = box(0, 22, 60, 25)  # тротуар 3 м
    path = box(26, 20, 28, 22)  # калитка
    features = [
        Feature(REF, name, g, object_class=ObjectClass.SIDEWALK)
        for name, g in {"ground": ground, "walk": walk, "path": path}.items()
    ]
    labels = [
        MaterialLabel(27, 13, "ДЕТ.ПЛ.", "paved"),
        MaterialLabel(27, 11, "СПЕЦ.ПОКР.", "paved"),
    ]
    labels += [MaterialLabel(x, 23.5, "А", "paved") for x in range(3, 60, 6)]
    kinds = _kinds(tmp_path, features, labels, [])
    assert kinds["special"].intersection(ground).area > 0.9 * ground.area
    assert kinds["special"].intersection(walk).area < 0.01


def _areas_with(
    tmp_path: Path, features: list[Feature], labels: list, basemap_features: list
) -> dict:
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
    return json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]


def test_flowerbed_island_in_a_plaza_stays_soil(tmp_path: Path) -> None:
    """Харьковская, площадка у дома 1А (пользователь, 19.10.2026: «стёр клумбу»): восьмиугольник
    «Газон устраиваемый» 27,8 м² посреди плиточной площади, внутри подпись съёмки «Ц» -
    карта покрытий снимала газон как противоречие. Газон-остров, со всех сторон окружённый
    покрытием, на показе - грунт; рядом подпись «КЛУМБА» - цветник."""
    plaza = box(10, 5, 40, 30)
    bed = Point(25, 17).buffer(3, quad_segs=2)  # восьмиугольник
    features = [Feature(REF, "plaza", plaza, object_class=ObjectClass.SIDEWALK)]
    # «КЛУМБА» на Харьковской стоит в 4 м от края восьмиугольника, у выноски.
    labels = [MaterialLabel(25, 17, "Ц", "paved"), MaterialLabel(32, 19, "КЛУМБА", "soil")]
    areas = _areas_with(
        tmp_path,
        features,
        labels,
        [BasemapFeature(ObjectClass.SIDEWALK, plaza), BasemapFeature(ObjectClass.LAWN, bed)],
    )
    soil = _union(areas["soil"])
    paved = _union(areas["paved"])
    assert soil.intersection(bed).area > 0.9 * bed.area
    assert paved.intersection(bed).area < 0.05 * bed.area
    assert _union(areas["flowerbeds"]).intersection(bed).area > 0.9 * bed.area


def test_lawn_strip_at_the_plaza_edge_is_not_an_island(tmp_path: Path) -> None:
    """Полоса газона вдоль края покрытия (старый газон под новым тротуаром) - не остров: решает
    карта покрытий, как раньше."""
    plaza = box(10, 5, 40, 30)
    strip = box(10, 5, 40, 6.5)
    features = [Feature(REF, "plaza", plaza, object_class=ObjectClass.SIDEWALK)]
    areas = _areas_with(
        tmp_path,
        features,
        [],
        [BasemapFeature(ObjectClass.SIDEWALK, plaza), BasemapFeature(ObjectClass.LAWN, strip)],
    )
    assert _union(areas["soil"]).intersection(strip).area < 0.1 * strip.area


def test_short_zigzag_is_not_rounded_into_a_wave() -> None:
    """Пила края без линии чертежа (звенья по полметра) скруглением Чайкина становилась волной
    (пользователь, 19.10.2026: «меня бесит волнистость»). Скругляется только настоящий
    поворот, где оба звена длиннее ROUND_MIN_SEG_M; короткие звенья остаются отрезками."""
    teeth = [(x * 0.6, 0.15 if x % 2 else 0.0) for x in range(21)]
    ring = [*teeth, (12.0, 10.0), (0.0, 10.0), teeth[0]]
    rounded = _round_turns(ring)
    assert all(pt in rounded for pt in teeth[1:-1])


def test_parking_corner_is_not_chamfered() -> None:
    """Стоянка у дома 1 корп. 1 на Харьковской - четырёхугольник с углами около 70-110°:
    срез Чайкина по четверти стороны (до 2,5 м) делал её «не квадратной» (пользователь,
    19.10.2026). Угол круче ROUND_MAX_TURN_DEG - угол, а не поворот дороги."""
    lot = [(0.0, 0.0), (10.0, 1.5), (12.0, -12.0), (2.0, -14.0), (0.0, 0.0)]
    assert _round_turns(lot) == lot


def test_road_bend_is_rounded_with_a_short_cut() -> None:
    """Поворот дороги скругляется, но срез не длиннее ROUND_CUT_M: длинная сторона не съедается."""
    bend = [(0.0, 0.0), (40.0, 0.0), (60.0, 15.0), (60.0, 40.0), (0.0, 40.0), (0.0, 0.0)]
    rounded = _round_turns(bend)
    assert (40.0, 0.0) not in rounded
    cut = [p for p in rounded if p[1] == 0.0 and 30.0 < p[0] < 40.0]
    assert cut
    assert min(p[0] for p in cut) > 38.9


def test_flowerbed_label_picks_the_small_island_not_the_big_lawn(tmp_path: Path) -> None:
    """Харьковская: «КЛУМБА» стоит у края большого газона рядом с круглой площадью; цветником
    стал весь газон 300 м² вместо клумбы в середине площади. Цветник - малый остров."""
    plaza = box(10, 5, 34, 30)
    bed = Point(25, 17).buffer(3, quad_segs=2)
    lawn = box(35, 5, 50, 25)  # 300 м² за краем площади, весь в дорожках
    walk = box(34, 5, 35, 30)
    ring = [walk, box(34, 4, 51, 5), box(50, 4, 51, 26), box(34, 25, 51, 26)]
    features = [
        Feature(REF, "plaza", plaza, object_class=ObjectClass.SIDEWALK),
        *(Feature(REF, "walk", w, object_class=ObjectClass.SIDEWALK) for w in ring),
    ]
    labels = [MaterialLabel(25, 17, "Ц", "paved"), MaterialLabel(33, 19, "КЛУМБА", "soil")]
    areas = _areas_with(
        tmp_path,
        features,
        labels,
        [
            BasemapFeature(ObjectClass.SIDEWALK, plaza),
            *(BasemapFeature(ObjectClass.SIDEWALK, w) for w in ring),
            BasemapFeature(ObjectClass.LAWN, bed),
            BasemapFeature(ObjectClass.LAWN, lawn),
        ],
    )
    beds = _union(areas["flowerbeds"])
    assert beds.intersection(bed).area > 0.9 * bed.area
    assert beds.intersection(lawn).area < 1


def test_lawn_island_survives_a_geos_topology_failure(monkeypatch) -> None:  # noqa: ANN001
    """Харьковский проезд, 19.10.2026: пересечение кольца газона с покрытием в GEOS упало
    («Ring edge missing»), и с ним весь прогон. Сбой повторяется на сетке 1 мм, а не роняет
    выгрузку."""
    real = shapely.intersection
    calls = {"n": 0}

    def flaky(a, b, **kwargs):  # noqa: ANN001, ANN003, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            raise shapely.errors.GEOSException("TopologyException: Ring edge missing")
        return real(a, b, **kwargs)

    plaza = box(10, 5, 40, 30)
    bed = Point(25, 17).buffer(3, quad_segs=2)
    ring = bed.buffer(1).difference(bed)
    monkeypatch.setattr(shapely, "intersection", flaky)
    covered = _overlap_areas([ring], plaza)
    assert covered[0] > 0.99 * ring.area


def test_subdivided_paved_keeps_its_area_in_small_pieces() -> None:
    """Покрытие улицы режется на куски не больше SUBDIVIDE_VERTICES вершин без потери площади."""
    street = Point(0, 0).buffer(500, quad_segs=2000).difference(Point(0, 0).buffer(200))
    pieces = _subdivided(street)
    assert len(pieces) > 1
    assert max(shapely.get_num_coordinates(p) for p in pieces) <= SUBDIVIDE_VERTICES
    assert abs(sum(p.area for p in pieces) - street.area) < 1e-6 * street.area
    assert shapely.union_all(pieces).symmetric_difference(street).area < 1e-6 * street.area


def test_lawn_islands_work_grows_with_the_street_not_street_times_lawns(monkeypatch) -> None:  # noqa: ANN001
    """Фрунзенская, 19.10.2026: 13 тыс. газонов, и кольцо каждого пересекалось с покрытием
    всей улицы - surface.json считался час. Кольцо меряется кусками покрытия рядом с ним:
    вершин через пересечения проходит порядка самого покрытия, а не покрытие на число газонов."""
    plaza = Point(0, 0).buffer(300, quad_segs=3000)
    beds = [
        Point(x, y).buffer(3, quad_segs=2)
        for x in range(-120, 121, 20)
        for y in range(-120, 121, 20)
    ]
    paved = plaza.difference(shapely.union_all(beds))
    basemap = Basemap(
        features=tuple(BasemapFeature(ObjectClass.LAWN, b) for b in beds),
        features_in=len(beds),
        features_out=len(beds),
        dropped={},
        bbox=plaza.bounds,
        labels=(),
    )
    work = {"coords": 0}
    real = shapely.intersection

    def counting(a, b, **kwargs):  # noqa: ANN001, ANN003, ANN202
        work["coords"] += int(np.sum(shapely.get_num_coordinates(a)))
        work["coords"] += int(np.sum(shapely.get_num_coordinates(b)))
        return real(a, b, **kwargs)

    monkeypatch.setattr(shapely, "intersection", counting)
    islands, _ = _lawn_islands(basemap, paved)
    assert islands is not None
    assert islands.area > 0.99 * sum(b.area for b in beds)
    assert work["coords"] < 20 * shapely.get_num_coordinates(paved)


def test_drawn_rounded_corners_keep_their_arcs(tmp_path: Path) -> None:
    """Харьковская, площадка у дома 1А (пользователь, 19.10.2026: «странные и кривые углы у
    площадки»): контур площадки в чертеже со скруглёнными углами, а сглаживание пилы растра
    (упрощение на полметра) превращало дуги в срезы и острые углы. Край, заданный контуром
    чертежа, идёт по чертежу: и выпуклые, и вогнутые скругления."""
    cross = shapely.union_all([box(10, 5, 30, 30), box(30, 15, 40, 25)])
    r = 0.8
    ground = cross.buffer(-r, quad_segs=8).buffer(r, quad_segs=8)
    ground = ground.buffer(r, quad_segs=8).buffer(-r, quad_segs=8)
    features = [Feature(REF, "ground", ground, object_class=ObjectClass.SIDEWALK)]
    surface = build_surface_map(features, [], SITE, 0.5)
    assert surface is not None
    basemap = Basemap(
        features=(BasemapFeature(ObjectClass.SIDEWALK, ground),),
        features_in=1,
        features_out=1,
        dropped={},
        bbox=SITE.bounds,
        labels=(),
    )
    _surface(tmp_path, surface, basemap)
    areas = json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]
    paved = _union(areas["paved"])
    assert paved.boundary.hausdorff_distance(ground.boundary) < 0.08


def test_lawn_strip_overlapping_the_playground_edge_does_not_bite_it(tmp_path: Path) -> None:
    """Харьковская, площадка у дома 1А: полоса газона между площадкой и оградой заходит на край
    площадки на 10-20 см и считалась островом среди покрытия - остров вырезал из площадки
    углы. Газон, лежащий больше чем наполовину вне контура покрытия чертежа, контур не режет;
    клумба внутри площади (test_flowerbed_island_in_a_plaza_stays_soil) режет."""
    ground = box(10, 5, 30, 25)
    strip = box(29.85, 5, 30.6, 25)  # газон у ограды, на 15 см на площадке
    walk = box(30.6, 0, 33, 30)  # тротуар за оградой
    features = [
        Feature(REF, "ground", ground, object_class=ObjectClass.SIDEWALK),
        Feature(REF, "walk", walk, object_class=ObjectClass.SIDEWALK),
    ]
    surface = build_surface_map(features, [], SITE, 0.5)
    assert surface is not None
    basemap = Basemap(
        features=(
            BasemapFeature(ObjectClass.SIDEWALK, ground),
            BasemapFeature(ObjectClass.SIDEWALK, walk),
            BasemapFeature(ObjectClass.LAWN, strip),
        ),
        features_in=3,
        features_out=3,
        dropped={},
        bbox=SITE.bounds,
        labels=(),
    )
    _surface(tmp_path, surface, basemap)
    areas = json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]
    paved = _union(areas["paved"])
    assert ground.difference(paved).area < 0.3


def test_rubber_is_the_drawn_playground_exactly(tmp_path: Path) -> None:
    """Харьковская, площадка у дома 1А: резина отделялась от дорожек размыканием на 1,5 м, и на
    стыке с дорожкой у калитки оставался клин резины, а угол площадки срезался. Есть контур
    площадки в чертеже с подписью площадки - резина ровно по нему, дорожка остаётся дорожкой."""
    ground = box(20, 6, 34, 20).buffer(-0.8, quad_segs=8).buffer(0.8, quad_segs=8)
    # Дорожка входит в площадку с расширением: в чертеже её край у площадки скруглён.
    joined = shapely.union_all([ground, box(26, 19, 27.5, 34)])
    path = joined.buffer(1.5, quad_segs=8).buffer(-1.5, quad_segs=8).difference(ground)
    features = [
        Feature(REF, "ground", ground, object_class=ObjectClass.SIDEWALK),
        Feature(REF, "path", path, object_class=ObjectClass.SIDEWALK),
    ]
    labels = (
        MaterialLabel(27, 13, "ДЕТ.ПЛ.", "paved"),
        MaterialLabel(27, 11, "СПЕЦ.ПОКРЫТИЕ", "paved"),
        MaterialLabel(26.7, 30, "А", "paved"),
    )
    surface = build_surface_map(features, [], SITE, 0.5)
    assert surface is not None
    basemap = Basemap(
        features=(
            BasemapFeature(ObjectClass.SIDEWALK, ground),
            BasemapFeature(ObjectClass.SIDEWALK, path),
        ),
        features_in=2,
        features_out=2,
        dropped={},
        bbox=SITE.bounds,
        labels=labels,
        paved_polygons=(ground, path),
    )
    _surface(tmp_path, surface, basemap)
    areas = json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]
    special = _union(
        [p for p, k in zip(areas["paved"], areas["paved_kind"], strict=True) if k == "special"]
    )
    assert special.boundary.hausdorff_distance(ground.boundary) < 0.08
    assert special.intersection(path.difference(ground)).area < 0.01


def test_drawn_contour_has_no_centimetre_segments(tmp_path: Path) -> None:
    """Харьковская, дом 1А: контур проезда из чертежа вышел с изломами по 1-2 см на углах (шов
    половин и швы буфера), и 3D, снимая вершины у звеньев короче 5 см, срезал по ним узкий
    вырез газона у ограды: земля там проваливалась под асфальт, а из него росла трава. Звенья
    контура - не короче нескольких сантиметров."""
    cross = shapely.union_all([box(10, 5, 30, 30), box(30, 15, 40, 25)])
    ground = cross.buffer(-0.8, quad_segs=8).buffer(0.8, quad_segs=8)
    features = [Feature(REF, "ground", ground, object_class=ObjectClass.SIDEWALK)]
    surface = build_surface_map(features, [], SITE, 0.5)
    assert surface is not None
    basemap = Basemap(
        features=(BasemapFeature(ObjectClass.SIDEWALK, ground),),
        features_in=1,
        features_out=1,
        dropped={},
        bbox=SITE.bounds,
        labels=(),
    )
    _surface(tmp_path, surface, basemap)
    areas = json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]
    for polygon in areas["paved"]:
        for ring in polygon:
            pts = np.asarray(ring)
            seg = np.hypot(*np.diff(pts, axis=0).T)
            assert seg.min() >= 0.04


def test_3d_surface_reaches_past_the_work_boundary() -> None:
    """Харьковская, 19.10.2026: дорожка от калитки площадки за границей работ обрывалась в газон,
    а тротуар у дома 1А за границей был газоном - карта покрытий кончается на границе работ.
    Для 3D карта строится шире границы на DISPLAY_MARGIN_M; посадки читают прежнюю."""
    boundary = box(0, 0, 30, 40)
    outside_walk = box(35, 0, 45, 40)
    features = [
        Feature(REF, "boundary", boundary, object_class=ObjectClass.WORK_BOUNDARY),
        Feature(REF, "walk", outside_walk, object_class=ObjectClass.SIDEWALK),
        Feature(REF, "lawn", box(2, 2, 28, 38), object_class=ObjectClass.LAWN),
    ]
    planning = build_surface_map(features, [], work_boundary(features), 0.5)
    display = build_surface_map(features, [], display_extent(work_boundary(features)), 0.5)
    assert planning is not None
    assert display is not None
    point = shapely.points([(40.0, 20.0)])
    assert not bool(shapely.intersects(planning.paved_area, point)[0])
    assert bool(shapely.intersects(display.paved_area, point)[0])
    assert DISPLAY_MARGIN_M >= 30


def test_3d_surface_past_the_boundary_does_not_flood_from_a_label() -> None:
    """За границей работ съёмка беднее линиями: подпись «ДЕТ.ПЛ.» в открытой области
    заливала покрытием всё до края рамки карты (Харьковская, 19.10.2026). В карте для показа
    подпись площадки заливает только область, замкнутую линиями чертежа."""
    boundary = box(0, 0, 30, 40)
    closed = box(45, 5, 55, 15)  # площадка, обведённая бортом
    features = [
        Feature(REF, "boundary", boundary, object_class=ObjectClass.WORK_BOUNDARY),
        Feature(REF, "lawn", box(2, 2, 28, 38), object_class=ObjectClass.LAWN),
        Feature(REF, "curb", closed.exterior, object_class=ObjectClass.CURB),
        # Полоса, открытая к краю рамки карты (граница работ + 40 м по x = 70): её замыкает
        # только рамка.
        Feature(
            REF,
            "curb2",
            LineString([(80, 20), (60, 20), (60, 35), (80, 35)]),
            object_class=ObjectClass.CURB,
        ),
    ]
    labels = [
        TextLabel(REF, "t", 50.0, 10.0, "ДЕТ.ПЛ."),
        TextLabel(REF, "t", 65.0, 27.0, "ДЕТ.ПЛ."),
    ]
    boundary = work_boundary(features)
    display = build_surface_map(
        features, labels, display_extent(boundary), 0.5, display_around=boundary
    )
    assert display is not None

    def material(x: float, y: float) -> Material:
        col = int((x - display.origin[0]) / display.cell)
        row = int((y - display.origin[1]) / display.cell)
        return Material(int(display.grid[row, col]))

    assert material(50, 10) is Material.PAVED
    assert material(65, 27) is not Material.PAVED
    assert material(68, 22) is not Material.PAVED


def test_3d_surface_past_the_boundary_does_not_spread_labels() -> None:
    """Харьковская, 19.10.2026: за границей работ лист съёмки обрывается, и подписи «А» и
    «ДЕТ.ПЛ.» разливались на 30 м в пустое место - за границей вырастало резиновое пятно в
    тысячу квадратных метров. В карте для показа подписи разливаются только в границе работ,
    за ней решают нарисованные контуры; в границе разлив тот же, что для посадок."""
    boundary = box(0, 0, 30, 40)
    walk = box(40, 30, 50, 34)  # нарисованная дорожка за границей
    features = [
        Feature(REF, "boundary", boundary, object_class=ObjectClass.WORK_BOUNDARY),
        Feature(REF, "walk", walk, object_class=ObjectClass.SIDEWALK),
    ]
    labels = [
        TextLabel(REF, "t", 10.0, 20.0, "А"),
        TextLabel(REF, "t", 50.0, 10.0, "А"),  # за границей, в пустом месте
    ]
    display = build_surface_map(
        features,
        labels,
        display_extent(boundary),
        0.5,
        inference_mode="hybrid",
        display_around=boundary,
    )
    planning = build_surface_map(features, labels, boundary, 0.5, inference_mode="hybrid")
    assert display is not None
    assert planning is not None

    def material(surface: object, x: float, y: float) -> Material:
        col = int((x - surface.origin[0]) / surface.cell)
        row = int((y - surface.origin[1]) / surface.cell)
        return Material(int(surface.grid[row, col]))

    assert material(display, 10, 30) is Material.PAVED
    assert material(planning, 10, 30) is Material.PAVED
    assert material(display, 50, 10) is Material.UNKNOWN
    assert material(display, 50, 18) is Material.UNKNOWN
    assert material(display, 45, 32) is Material.PAVED


def test_sports_ground_with_its_label_is_rubber_even_when_paths_vote_asphalt(
    tmp_path: Path,
) -> None:
    """Харьковская, 19.10.2026: спортплощадка «СПОРТ ПЛ.», «СПЕЦ.ПОКР.» с дорожкой, где две
    подписи «А», выходила асфальтом: тело площадки - почти вся часть, и решали голоса. Тело
    с подписью площадки и без подписей материала внутри - резина."""
    ground = box(20, 6, 32, 14)
    path = box(25.5, 14, 27, 24)
    features = [
        Feature(REF, "ground", ground, object_class=ObjectClass.SIDEWALK),
        Feature(REF, "path", path, object_class=ObjectClass.SIDEWALK),
    ]
    labels = [
        MaterialLabel(24, 10, "СПОРТ ПЛ.", "paved"),
        MaterialLabel(24, 8, "СПЕЦ.ПОКР.", "paved"),
        MaterialLabel(26.2, 18, "А", "paved"),
        MaterialLabel(26.2, 22, "А", "paved"),
    ]
    kinds = _kinds(tmp_path, features, labels, [])
    assert kinds["special"].intersection(ground).area > 0.9 * ground.area


def test_second_ground_without_a_drawn_contour_is_rubber_too(tmp_path: Path) -> None:
    """Харьковская, 19.10.2026: площадка у дома 1А обведена в чертеже, а спортплощадка за
    дорожкой - только подписями. Одна часть покрытия: тело взялось по контуру первой, а вторая
    ушла в остаток и стала асфальтом по «А» дорожки. Подпись площадки вне контура ищет своё
    тело размыканием остатка."""
    playground = box(20, 26, 34, 38)
    path = box(26, 14, 27.5, 26)
    sports = box(20, 4, 34, 14)
    features = [
        Feature(REF, "playground", playground, object_class=ObjectClass.SIDEWALK),
        Feature(REF, "path", path, object_class=ObjectClass.SIDEWALK),
        Feature(REF, "sports", sports, object_class=ObjectClass.SIDEWALK),
    ]
    labels = (
        MaterialLabel(27, 33, "ДЕТ.ПЛ.", "paved"),
        MaterialLabel(27, 31, "СПЕЦ.ПОКРЫТИЕ", "paved"),
        MaterialLabel(24, 9, "СПОРТ ПЛ.", "paved"),
        MaterialLabel(24, 7, "СПЕЦ.ПОКР.", "paved"),
        MaterialLabel(26.7, 18, "А", "paved"),
        MaterialLabel(26.7, 22, "А", "paved"),
    )
    surface = build_surface_map(features, [], SITE, 0.5)
    assert surface is not None
    basemap = Basemap(
        features=tuple(BasemapFeature(ObjectClass.SIDEWALK, g) for g in (playground, path, sports)),
        features_in=3,
        features_out=3,
        dropped={},
        bbox=SITE.bounds,
        labels=labels,
        paved_polygons=(playground,),
    )
    _surface(tmp_path, replace(surface, paved_area=None, soil_area=None), basemap)
    areas = json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]
    special = _union(
        [p for p, k in zip(areas["paved"], areas["paved_kind"], strict=True) if k == "special"]
    )
    assert special.intersection(playground).area > 0.9 * playground.area
    assert special.intersection(sports).area > 0.8 * sports.area


def test_drawn_contour_loses_a_small_zigzag(tmp_path: Path) -> None:
    """Харьковская, площадка у дома 1А (пользователь, 19.10.2026: «резкие переходы»): узкая
    выемка в контуре ломала садовый борт ступенькой. Выемки уже 0,3 м заливаются, прямые углы
    остаются."""
    zig = Polygon(
        [
            (10, 5),
            (30, 5),
            (30, 20),
            (21.0, 20),
            (20.9, 19.7),
            (20.8, 20),
            (10, 20),
        ]
    )
    features = [Feature(REF, "ground", zig, object_class=ObjectClass.SIDEWALK)]
    surface = build_surface_map(features, [], SITE, 0.5)
    assert surface is not None
    basemap = Basemap(
        features=(BasemapFeature(ObjectClass.SIDEWALK, zig),),
        features_in=1,
        features_out=1,
        dropped={},
        bbox=SITE.bounds,
        labels=(),
    )
    _surface(tmp_path, surface, basemap)
    areas = json.loads((tmp_path / "surface.json").read_text(encoding="utf-8"))["areas"]
    paved = _union(areas["paved"])
    dip = [y for x, y in shapely.get_coordinates(paved.boundary) if 20.4 < x < 21.4]
    assert all(y > 19.95 for y in dip)
    assert paved.contains(Point(20.9, 19.8))
    assert paved.contains(Point(29.8, 5.2))  # прямой угол остался


def test_tiny_part_is_dropped_with_its_kind_not_exported_as_a_broken_ring() -> None:
    """Понтрягина, 19.10.2026: после снятия звеньев короче 5 см у крошечной части оставалось
    меньше четырёх точек кольца, и такая «часть» ломала чтение surface.json. Кольца в выгрузке
    - не меньше четырёх точек, вид части при этом не съезжает."""
    tiny = Polygon([(0, 0), (0.04, 0), (0.04, 0.03), (0, 0)])
    big = box(10, 10, 20, 20)
    rings = [_polygon_rings(tiny), _polygon_rings(big)]
    kept = _export_parts([tiny, big], ["asphalt", "pavers"])
    assert len(rings[0][0]) < 4
    assert kept[1] == ["pavers"]
    assert all(len(ring) >= 4 for polygon in kept[0] for ring in polygon)


def test_walk_end_in_a_road_notch_goes_to_the_road() -> None:
    """Кустанайская, 19.10.2026: дорожка нарисована дальше борта, её конец стоял островом в
    опущенном проезде, и борт обходил его прямоугольником. Конец в выемке проезда - проезд."""
    road = box(0, 0, 40, 10).difference(box(19, 6, 21.5, 10))  # выемка под конец дорожки
    walk = box(19.2, 6.2, 21.3, 30)  # дорожка заходит в выемку на 3,8 м
    parts, kinds = _walk_ends_to_road([road, walk], ["road", "asphalt"])
    roads = shapely.union_all([p for p, k in zip(parts, kinds, strict=True) if k == "road"])
    walks = shapely.union_all([p for p, k in zip(parts, kinds, strict=True) if k == "asphalt"])
    assert walks.bounds[1] >= 9.0
    assert roads.contains(Point(20.2, 7.5))
    assert walks.area > 0.9 * box(19.2, 10, 21.3, 30).area


def test_small_hole_in_paving_is_filled_but_a_lawn_island_stays() -> None:
    """Дыра в проезде от знака колодца или обрезка дорожки - не остров: борт в 3D обходил её
    кольцом посреди асфальта. Газон-остров той же величины остаётся дырой."""
    well = box(10, 4, 11.5, 5)
    island = box(30, 4, 31.5, 5.5)
    road = box(0, 0, 40, 10).difference(well).difference(island)
    out = _without_artifact_holes(road, island)
    assert len(out.interiors) == 1
    assert out.contains(Point(10.7, 4.5))
    assert not out.contains(Point(30.7, 4.7))


def test_porch_notch_of_a_walk_is_paved_but_lawn_and_corners_stay() -> None:
    """Харьковская, 19.10.2026: у входа в дом крыльцо нарисовано линиями без материала,
    выемка дорожки оставалась неизвестной, и в 3D у крыльца стоял островок травы. Узкая
    выемка мостится; газон в такой же выемке и внутренний угол дорожки не трогаются."""
    walk = box(0, 0, 3, 20).difference(box(2, 8, 3, 10.5))  # крыльцо 1 x 2,5 м
    lawn_bay = box(2, 14, 3, 16)
    walk = walk.difference(lawn_bay)
    corner = box(0, 0, 10, 3)  # дорожка уходит вбок: внутренний угол
    walk = shapely.union_all([walk, corner])
    out = _walk_notches_paved([walk], ["asphalt"], lawn_bay, None)[0]
    assert out.contains(Point(2.5, 9.2))
    assert not out.contains(Point(2.5, 15))
    assert not out.contains(Point(3.5, 3.5))


def test_labelled_dashed_circle_is_a_flowerbed() -> None:
    """Харьковская, 19.10.2026: клумба нарисована пунктирным кругом слоя «Топографические
    объекты» с подписью «КЛУМБА» внутри. Сшитый круг - замкнутый контур, клумба - он сам, а
    не газон вокруг; круг без подписи клумбой не становится."""
    bed = Point(10, 10).buffer(1.5)
    other = Point(30, 10).buffer(1.5)
    basemap = Basemap(
        features=(
            BasemapFeature(ObjectClass.LAWN, box(0, 0, 40, 20)),
            BasemapFeature(ObjectClass.OBSTACLE, LineString(bed.exterior.coords), dashed=True),
            BasemapFeature(ObjectClass.OBSTACLE, LineString(other.exterior.coords), dashed=True),
        ),
        features_in=3,
        features_out=3,
        dropped={},
        bbox=(0, 0, 40, 20),
        labels=(MaterialLabel(9.4, 9.6, "КЛУМБА", "soil"),),
    )
    beds = _drawn_beds(basemap)
    assert beds is not None
    assert beds.symmetric_difference(bed).area < 0.05 * bed.area
    assert not beds.intersects(other)


def test_label_past_the_boundary_fills_a_face_closed_by_drawn_lines() -> None:
    """Харьковская, 19.10.2026: полоса «Ц» (цементобетон) между оградой и стеной школы лежит
    за границей работ и в 3D стояла газоном. За границей подпись разливается только в грани,
    которую замыкают линии чертежа; открытое к рамке место по-прежнему не заливается."""
    boundary = box(0, 0, 30, 40)
    yard = [
        LineString([(35, 5), (45, 5), (45, 15), (35, 15), (35, 5)]),  # ограда и стены
    ]
    features = [
        Feature(REF, "boundary", boundary, object_class=ObjectClass.WORK_BOUNDARY),
        *(Feature(REF, "fence", g, object_class=ObjectClass.FENCE) for g in yard),
    ]
    labels = [
        TextLabel(REF, "t", 10.0, 20.0, "А"),
        TextLabel(REF, "t", 40.0, 10.0, "Ц"),  # в замкнутой грани за границей
        TextLabel(REF, "t", 50.0, 30.0, "А"),  # за границей, в пустом месте
    ]
    display = build_surface_map(
        features,
        labels,
        display_extent(boundary),
        0.5,
        inference_mode="hybrid",
        display_around=boundary,
    )
    assert display is not None

    def material(x: float, y: float) -> Material:
        col = int((x - display.origin[0]) / display.cell)
        row = int((y - display.origin[1]) / display.cell)
        return Material(int(display.grid[row, col]))

    assert material(42, 12) is Material.PAVED
    assert material(50, 25) is Material.UNKNOWN


def test_nearly_closed_flowerbed_outline_still_holds_the_bed() -> None:
    """Харьковская: контур клумбы недозамкнут на 11 см - это всё ещё клумба."""
    ring = list(Point(10, 10).buffer(2.0).exterior.coords)[:-2]  # концы разошлись
    basemap = Basemap(
        features=(BasemapFeature(ObjectClass.OBSTACLE, LineString(ring), dashed=True),),
        features_in=1,
        features_out=1,
        dropped={},
        bbox=(0, 0, 20, 20),
        labels=(MaterialLabel(9.0, 9.5, "КЛУМБА", "soil"),),
    )
    beds = _drawn_beds(basemap)
    assert beds is not None
    assert beds.area > 0.8 * Point(10, 10).buffer(2.0).area


def test_round_dashed_contour_with_a_lawn_mark_is_a_bed() -> None:
    """Харьковская: у парковки дома пунктирный круг со знаком травяного покрова внутри, без
    подписи. Это круглая клумба; газон со своим знаком и некруглый контур клумбой не становятся."""
    circle = Point(10, 10).buffer(2.2)
    square = box(20, 5, 30, 15)
    basemap = Basemap(
        features=(
            BasemapFeature(ObjectClass.LAWN, box(0, 0, 40, 20)),
            BasemapFeature(ObjectClass.OBSTACLE, LineString(circle.exterior.coords), dashed=True),
            BasemapFeature(ObjectClass.OBSTACLE, LineString(square.exterior.coords), dashed=True),
            BasemapFeature(ObjectClass.LAWN, Point(10, 10)),
            BasemapFeature(ObjectClass.LAWN, Point(25, 10)),
            BasemapFeature(ObjectClass.LAWN, Point(35, 10)),
        ),
        features_in=6,
        features_out=6,
        dropped={},
        bbox=(0, 0, 40, 20),
    )
    beds = _drawn_beds(basemap)
    assert beds is not None
    assert beds.contains(Point(10, 10))
    assert not beds.intersects(Point(25, 10))
    assert not beds.contains(Point(35, 10))


def test_a_multipart_paved_part_exports_as_parts_of_its_kind() -> None:
    """Чертёж жюри 236287.dxf, 19.10.2026: выемка у крыльца, присоединённая к дорожке углом,
    оставила мультиполигон, и выгрузка покрытий падала на нём. Каждый кусок - своя часть."""
    two = MultiPolygon([box(0, 0, 5, 2), box(5, 2, 8, 6)])
    rings, kinds = _export_parts([two, box(20, 0, 30, 5)], ["asphalt", "road"])
    assert kinds == ["asphalt", "asphalt", "road"]
    assert len(rings) == 3
