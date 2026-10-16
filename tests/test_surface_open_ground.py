"""Чертёж без единого признака грунта: свободная земля в границе работ - газон с пометкой.

Входы других финалистов (17.10.2026): у синтетических участков greenai, green-atlas,
greenleaves, GreenCAD есть граница работ, дороги и дома, но нет ни газонов, ни подписей грунта.
План выходил пустым («Грунт не определён»). Теперь земля внутри границы без зданий и твёрдых
покрытий считается газоном, это видно в предупреждении «Исправлено автоматически», а посадки
остаются неподтверждёнными по грунту (эскиз).
"""

from __future__ import annotations

import shapely
from shapely.geometry import box

from green.application.surfaces import Material, build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef

REF = SourceRef("f", "x", "1")
SITE = box(0, 0, 100, 100)


def _features(*, lawn: bool = False) -> list[Feature]:
    items = [
        Feature(REF, "ROAD", box(0, 0, 100, 10), object_class=ObjectClass.ROAD),
        Feature(REF, "BUILDING", box(40, 40, 60, 60), object_class=ObjectClass.BUILDING),
    ]
    if lawn:
        items.append(Feature(REF, "GRASS", box(70, 70, 90, 90), object_class=ObjectClass.LAWN))
    return items


def _material(surface, x: float, y: float) -> Material:  # noqa: ANN001
    return Material(int(surface.material(shapely.points([(x, y)]))[0]))


def test_free_ground_inside_the_boundary_becomes_soil_with_a_note() -> None:
    surface = build_surface_map(_features(), [], SITE, 1.0)
    assert surface is not None
    assert _material(surface, 20, 50) is Material.SOIL
    assert _material(surface, 50, 50) is not Material.SOIL  # дом
    assert _material(surface, 50, 5) is not Material.SOIL  # проезжая часть
    notes = surface.review_notes()
    assert notes
    assert notes[0].startswith("Исправлено автоматически")
    assert not any(n.startswith("Грунт не определён") for n in notes)
    # Подтверждённым грунтом это не считается: посадки на нём - эскиз.
    assert not surface.fits_confirmed_soil(shapely.points([(20.0, 50.0)]), 0.0)[0]


def test_drawing_with_any_lawn_keeps_the_strict_reading() -> None:
    surface = build_surface_map(_features(lawn=True), [], SITE, 1.0)
    assert surface is not None
    assert _material(surface, 80, 80) is Material.SOIL
    assert _material(surface, 20, 50) is not Material.SOIL


def test_open_ground_can_be_switched_off() -> None:
    surface = build_surface_map(_features(), [], SITE, 1.0, open_ground=False)
    assert surface is None or _material(surface, 20, 50) is not Material.SOIL
