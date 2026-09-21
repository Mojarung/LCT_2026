"""Подоснова для карты в вебе: что попадает на канву и что отбрасывается.

Главная проверка — баланс: каждый объект сцены либо попал в карту, либо посчитан в отброшенных.
Карта, показывающая только то, что осталось, не отличает успешный отбор от молчаливой потери.
"""

from __future__ import annotations

from shapely.geometry import LineString, Point, Polygon

from green.application.basemap import build_basemap
from green.domain.objects import Feature, ObjectClass, SourceRef


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
