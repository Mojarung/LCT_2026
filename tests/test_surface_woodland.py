"""Знаки газона и насаждений - признак материала грани, как подпись.

Газон на подоснове помечен не подписью, а знаком GAZON внутри контура; без него грань
оставалась неизвестной и посадки в ней не было. Знак массива (LISTVL, SM) - тоже грунт, но
занятый существующими деревьями: сажать внутрь массива нельзя (Кустанайская, 24.09.2026).
"""

from __future__ import annotations

from dataclasses import replace

import shapely
from shapely.geometry import LineString, Point, box
from test_surface_uncertainty import feature

from green.application.surfaces import Material, build_surface_map
from green.domain.objects import ObjectClass

BORDERS = [
    LineString([(0, 0), (40, 0)]),
    LineString([(40, 0), (40, 20)]),
    LineString([(40, 20), (0, 20)]),
    LineString([(0, 20), (0, 0)]),
    LineString([(20, 0), (20, 20)]),
]
LAWN_FACE, WOODLAND_FACE = (10, 10), (30, 10)


def _surface(*markers: tuple[ObjectClass, tuple[float, float]]):  # noqa: ANN202
    features = [feature(ObjectClass.CURB, line, f"curb{i}") for i, line in enumerate(BORDERS)]
    features += [
        replace(feature(kind, Point(xy), kind.value), source_entity_type="SYMBOL_MARKER")
        for kind, xy in markers
    ]
    surface = build_surface_map(features, [], box(-2, -2, 42, 22), 0.5)
    assert surface is not None
    return surface


def test_faces_without_evidence_stay_unknown() -> None:
    surface = build_surface_map(
        [feature(ObjectClass.CURB, line, f"curb{i}") for i, line in enumerate(BORDERS)],
        [],
        box(-2, -2, 42, 22),
        0.5,
    )

    assert surface is None or surface.material(shapely.points([LAWN_FACE])).tolist() == [
        Material.UNKNOWN
    ]


def test_lawn_symbol_makes_its_closed_face_soil() -> None:
    surface = _surface((ObjectClass.LAWN, LAWN_FACE))

    points = shapely.points([LAWN_FACE, WOODLAND_FACE])
    assert surface.material(points).tolist() == [Material.SOIL, Material.UNKNOWN]
    assert surface.fits_soil(points, 1.6).tolist() == [True, False]


def test_woodland_symbol_face_is_soil_but_not_for_planting() -> None:
    surface = _surface(
        (ObjectClass.LAWN, LAWN_FACE), (ObjectClass.EXISTING_WOODLAND, WOODLAND_FACE)
    )

    points = shapely.points([LAWN_FACE, WOODLAND_FACE])
    assert surface.material(points).tolist() == [Material.SOIL, Material.SOIL]
    assert surface.fits_soil(points, 1.6).tolist() == [True, False]
    assert surface.fits_soil(points, 0.0).tolist() == [True, False]
    assert surface.woodland_area is not None
    assert surface.woodland_area.contains(Point(WOODLAND_FACE))
