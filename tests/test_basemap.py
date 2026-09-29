"""Подоснова для карты в вебе: что попадает на канву и что отбрасывается.

Главная проверка — баланс: каждый объект сцены либо попал в карту, либо посчитан в отброшенных.
Карта, показывающая только то, что осталось, не отличает успешный отбор от молчаливой потери.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

from shapely.geometry import LineString, Point, Polygon

from green.application.basemap import (
    DEFAULT_TOLERANCE_M,
    MAX_DETAIL_CUT,
    SMALL,
    SPAN_FLOOR_M,
    build_basemap,
)
from green.application.tree_strips import chain_tree_strips
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.infrastructure.reports.artifacts import FileArtifactSink, _basemap

if TYPE_CHECKING:
    from pathlib import Path


def _ref(handle: str) -> SourceRef:
    return SourceRef(file_sha8="aaaaaaaa", xref_hash8="00000000", handle=handle)


def _scene(features: list[Feature]) -> list[Feature]:
    """Подоснова строится по классифицированным объектам, отдельная сцена тут не нужна."""
    return features


def _feature(handle: str, object_class: ObjectClass, geometry: object) -> Feature:
    return Feature(
        ref=_ref(handle),
        layer="слой",
        geometry=geometry,  # type: ignore[arg-type]
        object_class=object_class,
    )


def test_hidden_classes_do_not_reach_the_map() -> None:
    scene = _scene(
        [
            _feature("1", ObjectClass.CURB, LineString([(0, 0), (100, 0)])),
            _feature("2", ObjectClass.UTILITY_WATER, LineString([(0, 10), (100, 10)])),
            _feature("3", ObjectClass.IGNORE, LineString([(0, 20), (100, 20)])),
            _feature("4", ObjectClass.UNKNOWN, Point(5, 5)),
        ]
    )

    basemap = build_basemap(scene)

    classes = {f.object_class for f in basemap.features}
    assert classes == {ObjectClass.CURB, ObjectClass.UTILITY_WATER}


def test_every_feature_is_accounted_for() -> None:
    scene = _scene(
        [
            _feature("1", ObjectClass.CURB, LineString([(0, 0), (100, 0)])),
            _feature("2", ObjectClass.IGNORE, LineString([(0, 20), (100, 20)])),
            _feature("3", ObjectClass.UNKNOWN, Point(5, 5)),
            _feature("4", ObjectClass.BUILDING, Polygon([(0, 30), (10, 30), (10, 40), (0, 40)])),
        ]
    )

    basemap = build_basemap(scene)

    assert basemap.features_in == 4
    assert basemap.features_out == len(basemap.features)
    assert basemap.features_out + sum(basemap.dropped.values()) == basemap.features_in


def test_simplification_keeps_the_shape_and_drops_degenerate_geometry() -> None:
    zigzag = LineString([(x, 0.01 if x % 2 else 0.0) for x in range(100)])
    speck = LineString([(0, 0), (0.001, 0.001)])
    scene = _scene(
        [
            _feature("1", ObjectClass.CURB, zigzag),
            _feature("2", ObjectClass.CURB, speck),
        ]
    )

    basemap = build_basemap(scene, tolerance_m=0.15)

    kept = [f for f in basemap.features if not f.geometry.is_empty]
    assert len(kept) == 1
    assert len(kept[0].geometry.coords) < len(zigzag.coords)
    assert basemap.features_out + sum(basemap.dropped.values()) == basemap.features_in


def test_bbox_covers_the_kept_geometry_only() -> None:
    scene = _scene(
        [
            _feature("1", ObjectClass.CURB, LineString([(0, 0), (50, 0)])),
            _feature("2", ObjectClass.IGNORE, LineString([(0, 0), (900, 900)])),
        ]
    )

    basemap = build_basemap(scene)

    assert basemap.bbox == (0.0, 0.0, 50.0, 0.0)


def test_coordinates_are_snapped_to_the_centimetre_grid() -> None:
    """Длинная координата утраивает вес выгрузки: на Берзарина 33,6 МБ против 12,9 МБ."""
    line = LineString([(0.123456789, 0.987654321), (50.111111111, 0.987654321)])
    scene = _scene([_feature("1", ObjectClass.CURB, line)])

    basemap = build_basemap(scene, precision_m=0.01)

    for x, y in basemap.features[0].geometry.coords:
        assert repr(x) == repr(round(x, 2))
        assert repr(y) == repr(round(y, 2))


def test_empty_scene_gives_an_empty_map_without_raising() -> None:
    basemap = build_basemap(_scene([]))

    assert basemap.features == ()
    assert basemap.features_in == 0
    assert basemap.features_out == 0
    assert basemap.bbox == (0.0, 0.0, 0.0, 0.0)


def _heavy(count: int) -> list[Feature]:
    """Чертёж сверх бюджета: длинные сети вперемешку с обломками условных знаков."""
    features: list[Feature] = []
    for i in range(count):
        # Обломок длиннее допуска упрощения: иначе он отсеется как вырожденный и до
        # порога мелочи дело не дойдёт.
        small = i % 2 == 0
        geometry = (
            LineString([(i, 0), (i + 0.4, 0.4)]) if small else LineString([(i, 10), (i + 30, 10)])
        )
        features.append(_feature(str(i), ObjectClass.UTILITY_WATER, geometry))
    return features


def test_light_drawing_keeps_the_default_detail() -> None:
    """Обычный чертёж огрублять незачем: порог мелочи выключен, допуск прежний."""
    basemap = build_basemap(_heavy(40), feature_budget=100)

    assert basemap.tolerance_m == DEFAULT_TOLERANCE_M
    assert basemap.min_span_m == 0.0
    assert basemap.features_out == 40


def test_heavy_drawing_is_coarser_and_drops_the_smallest() -> None:
    """Чертёж вчетверо тяжелее бюджета теряет мелочь, и потеря посчитана, а не молчалива."""
    basemap = build_basemap(_heavy(40), feature_budget=10)

    assert basemap.tolerance_m == round(DEFAULT_TOLERANCE_M * 2, 3)
    assert basemap.min_span_m == round(SPAN_FLOOR_M * 2, 3)
    assert basemap.dropped[SMALL] == 20
    assert basemap.features_out == 20
    assert basemap.features_out + sum(basemap.dropped.values()) == basemap.features_in


def test_detail_is_cut_no_further_than_the_limit() -> None:
    """У генплана огрубление упирается в потолок: подоснова обязана остаться читаемой."""
    basemap = build_basemap(_heavy(40), feature_budget=1)

    assert basemap.tolerance_m == round(DEFAULT_TOLERANCE_M * MAX_DETAIL_CUT, 3)
    assert basemap.min_span_m == round(SPAN_FLOOR_M * MAX_DETAIL_CUT, 3)


def test_point_symbols_survive_the_size_floor() -> None:
    """Опора и колодец мельче порога по определению, но именно от них считаются отступы."""
    poles = [_feature(f"p{i}", ObjectClass.POLE, Point(i, 0)) for i in range(40)]

    basemap = build_basemap(poles, feature_budget=10)

    assert basemap.min_span_m > 0
    assert basemap.features_out == len(poles)
    assert SMALL not in basemap.dropped


def test_conifer_symbols_are_marked_for_the_map() -> None:
    """Знак хвойного из съёмки доезжает до карты признаком, лиственный и прочие - без него."""
    pine = replace(
        _feature("t1", ObjectClass.EXISTING_TREE, Point(0, 0)),
        block="SOSNOD_12",
    )
    spruce = replace(
        _feature("t2", ObjectClass.EXISTING_TREE, Point(5, 0)),
        block="ELOD_3_1",
    )
    linden = replace(
        _feature("t3", ObjectClass.EXISTING_TREE, Point(10, 0)),
        block="DEREVO_935",
    )
    unnamed = _feature("t4", ObjectClass.EXISTING_TREE, Point(15, 0))
    # Код хвойного у куста или опоры - не хвойное дерево: признак только у класса дерева.
    shrub = replace(
        _feature("s1", ObjectClass.EXISTING_SHRUB, Point(20, 0)),
        block="SOSNOD_1",
    )

    basemap = build_basemap([pine, spruce, linden, unnamed, shrub])

    assert [f.conifer for f in basemap.features] == [True, True, False, False, False]
    assert basemap.features_out == 5


def test_the_conifer_mark_is_written_only_where_it_is(tmp_path: Path) -> None:
    pine = replace(_feature("t1", ObjectClass.EXISTING_TREE, Point(0, 0)), block="TUYA_2")
    linden = _feature("t2", ObjectClass.EXISTING_TREE, Point(5, 0))

    path = FileArtifactSink().save_basemap(tmp_path, build_basemap([pine, linden]))

    features = json.loads(path.read_text(encoding="utf-8"))["features"]
    assert [f["properties"] for f in features] == [
        {"class": "existing_tree", "conifer": True, "vegetation_kind": "individual"},
        {"class": "existing_tree", "vegetation_kind": "individual"},
    ]


def test_tree_strip_semantics_survive_basemap_export() -> None:
    features = [
        replace(
            _feature(str(i), ObjectClass.EXISTING_TREE, Point(i * 0.8, 0)), layer="Полоса деревьев"
        )
        for i in range(4)
    ]
    features.append(_feature("single", ObjectClass.EXISTING_TREE, Point(20, 10)))
    payload = _basemap(build_basemap(chain_tree_strips(features)))
    strips = [f for f in payload["features"] if f["properties"]["vegetation_kind"] == "strip"]
    singles = [f for f in payload["features"] if f["properties"]["vegetation_kind"] == "individual"]
    assert len(strips) == len(singles) == 1
    assert strips[0]["geometry"]["type"] == "MultiPoint"
    assert len(strips[0]["geometry"]["coordinates"]) == 4
    assert singles[0]["geometry"]["coordinates"] == [20, 10]
