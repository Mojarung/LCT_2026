"""Чертёж без единого признака грунта: свободная земля в границе работ - газон с пометкой.

Сторонние входы (17.10.2026): у синтетических участков greenai, green-atlas,
greenleaves, GreenCAD есть граница работ, дороги и дома, но нет ни газонов, ни подписей грунта.
План выходил пустым («Грунт не определён»). Теперь земля внутри границы без зданий и твёрдых
покрытий считается газоном, это видно в предупреждении «Исправлено автоматически», а посадки
остаются неподтверждёнными по грунту (эскиз).
"""

from __future__ import annotations

import shapely
from shapely.geometry import LineString, box

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


# Синтетические участки сторонних авторов (17.10.2026): дороги и тротуары линиями, без полигонов.
def _line(cls: ObjectClass, *xy: tuple[float, float]) -> Feature:
    return Feature(REF, cls.value, LineString(xy), object_class=cls)


def test_pairs_of_edge_lines_cut_the_carriageway_and_the_sidewalk() -> None:
    """greenai: две линии проезжей части (8 и 14 м), две линии тротуара (20 и 23 м), между
    ними полоса с опорами - газон; полоса от края до границы работ - тоже проезд (осторожно)."""
    site = box(0, 0, 120, 60)
    features = [
        _line(ObjectClass.ROAD, (0, 8), (120, 8)),
        _line(ObjectClass.ROAD, (0, 14), (120, 14)),
        _line(ObjectClass.SIDEWALK, (0, 20), (120, 20)),
        _line(ObjectClass.SIDEWALK, (0, 23), (120, 23)),
        Feature(REF, "B", box(10, 40, 45, 56), object_class=ObjectClass.BUILDING),
    ]
    surface = build_surface_map(features, [], site, 0.5)
    assert surface is not None
    assert _material(surface, 60, 11) is not Material.SOIL  # проезжая часть
    assert _material(surface, 60, 4) is not Material.SOIL  # от края проезда до границы
    assert _material(surface, 60, 21.5) is not Material.SOIL  # тротуар
    assert _material(surface, 60, 17) is Material.SOIL  # полоса между проездом и тротуаром
    assert _material(surface, 80, 40) is Material.SOIL
    assert _material(surface, 30, 50) is not Material.SOIL  # дом


def test_single_road_line_along_the_boundary_takes_the_narrow_side() -> None:
    surface = build_surface_map(
        [_line(ObjectClass.ROAD, (0, 5), (80, 5))], [], box(0, 0, 80, 50), 0.5
    )
    assert surface is not None
    assert _material(surface, 40, 2) is not Material.SOIL
    assert _material(surface, 40, 30) is Material.SOIL


def test_single_road_line_across_the_site_is_an_axis() -> None:
    """Обе стороны широкие - линия считается осью проезда шириной 7 м."""
    features = [_line(ObjectClass.ROAD, (0, 50), (100, 50))]
    surface = build_surface_map(features, [], SITE, 0.5)
    assert surface is not None
    assert _material(surface, 50, 48) is not Material.SOIL
    assert _material(surface, 50, 53) is not Material.SOIL
    assert _material(surface, 50, 20) is Material.SOIL
    assert _material(surface, 50, 80) is Material.SOIL


def test_closed_unknown_ring_is_cut_out_instead_of_blocking() -> None:
    """Водоём или контур без смысла замкнутым кольцом: внутри не сажаем, снаружи - газон."""
    ring = Feature(
        REF,
        "X",
        LineString([(60, 60), (80, 60), (80, 80), (60, 80), (60, 60)]),
        object_class=ObjectClass.CONTOUR,
    )
    surface = build_surface_map([ring], [], SITE, 0.5)
    assert surface is not None
    assert _material(surface, 70, 70) is not Material.SOIL
    assert _material(surface, 20, 20) is Material.SOIL


def test_building_drawn_as_closed_line_is_not_ground() -> None:
    """greenleaves: дом полилинией с совпадающими концами без флага замкнутости."""
    house = Feature(
        REF,
        "B",
        LineString([(55, 30), (75, 30), (75, 45), (55, 45), (55, 30)]),
        object_class=ObjectClass.BUILDING,
    )
    surface = build_surface_map([house], [], SITE, 0.5)
    assert surface is not None
    assert _material(surface, 65, 37) is not Material.SOIL
    assert _material(surface, 20, 20) is Material.SOIL


def test_open_unknown_lines_still_keep_the_strict_reading() -> None:
    line = Feature(REF, "X", LineString([(0, 30), (100, 35)]), object_class=ObjectClass.CONTOUR)
    surface = build_surface_map([line], [], SITE, 0.5)
    assert surface is None or _material(surface, 20, 70) is not Material.SOIL


def test_ignored_area_is_cut_out_instead_of_blocking() -> None:
    """GreenCity: разметка полигонами (слой ROAD_MARKINGS - оформление) запрещала весь запасной
    грунт. Площадь оформления вырезается, остальная земля - газон."""
    marks = Feature(REF, "ROAD_MARKINGS", box(60, 60, 80, 62), object_class=ObjectClass.IGNORE)
    surface = build_surface_map([marks], [], SITE, 0.5)
    assert surface is not None
    assert _material(surface, 70, 61) is not Material.SOIL
    assert _material(surface, 20, 20) is Material.SOIL


def test_sheet_frame_around_the_site_is_not_cut_out() -> None:
    frame = Feature(
        REF,
        "Рамка",
        LineString([(-5, -5), (105, -5), (105, 105), (-5, 105), (-5, -5)]),
        object_class=ObjectClass.IGNORE,
    )
    surface = build_surface_map([frame], [], SITE, 0.5)
    assert surface is not None
    assert _material(surface, 20, 20) is Material.SOIL


def test_ignored_copy_of_the_boundary_is_not_cut_out() -> None:
    """GreenCAD: GC_TEST_GREEN_ZONE - копия границы работ; вырезать её - значит вырезать всё."""
    copy = Feature(REF, "GC_TEST_GREEN_ZONE", SITE, object_class=ObjectClass.IGNORE)
    surface = build_surface_map([copy], [], SITE, 0.5)
    assert surface is not None
    assert _material(surface, 20, 20) is Material.SOIL


def test_ignored_copy_of_one_of_two_boundaries_is_not_cut_out() -> None:
    """GreenCAD, полный коридор: две границы работ и по копии каждой - копии не вырезаются."""
    left, right = box(0, 0, 50, 100), box(60, 0, 100, 100)
    features = [
        Feature(REF, "B1", left, object_class=ObjectClass.WORK_BOUNDARY),
        Feature(REF, "B2", right, object_class=ObjectClass.WORK_BOUNDARY),
        Feature(REF, "Z1", left, object_class=ObjectClass.IGNORE),
        Feature(REF, "Z2", right, object_class=ObjectClass.IGNORE),
    ]
    surface = build_surface_map(features, [], shapely.union_all([left, right]), 0.5)
    assert surface is not None
    assert _material(surface, 20, 20) is Material.SOIL
    assert _material(surface, 80, 20) is Material.SOIL
