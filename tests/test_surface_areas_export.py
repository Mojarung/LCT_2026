"""Карта покрытий отдаёт и контуры: 3D-вид рисует проезды и газоны прямыми краями.

Растр карты покрытий - клетки 0,5-1 м: край асфальта на 3D-виде выходил лесенкой, «как будто
кто-то отгрыз» (пользователь, 17.10.2026). Контуры грунта и покрытия, из которых растр и
закрашен, теперь лежат в surface.json (areas): клиент рисует их поверх растра.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import shapely
from shapely.geometry import Point, Polygon, box

from green.application.basemap import Basemap, BasemapFeature, MaterialLabel
from green.application.surfaces import build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.reports.artifacts import (
    _round_turns,
    _share_paved,
    _smoothed,
    _surface,
    _tidy,
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
    # Узкая полоса без подписи - тротуар плиткой целиком: раньше 3D делил её по ширине
    # попиксельно, и граница плитки и асфальта шла пятнами (пользователь, 19.10.2026).
    assert kinds["pavers"].intersection(strips["path"]).area > 0.8 * strips["path"].area
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


def test_narrow_asphalt_across_the_curb_is_a_tiled_sidewalk(tmp_path: Path) -> None:
    """Пользователь 19.10.2026: «то, что идёт с бордюром, меняется с асфальта на тротуар».
    Узкий асфальт в метре от проезжей части - тротуар плиткой; широкий (стоянка) плиткой не
    становится, дорожка вдали от проезда - асфальт. Решается целиком по части, а не по пикселю."""
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
    assert kinds["pavers"].intersection(strips["walk"]).area > 0.8 * strips["walk"].area
    assert kinds["pavers"].intersection(strips["parking"]).area < 0.01
    assert kinds["asphalt"].intersection(strips["path"]).area > 0.8 * strips["path"].area


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
    monkeypatch.setattr(shapely, "intersection", flaky)
    share = _share_paved(bed.buffer(1).difference(bed), plaza)
    assert share > 0.99
