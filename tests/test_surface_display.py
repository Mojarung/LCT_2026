"""Карта покрытий для показа: грани между линиями чертежа (surfaces.display_grid).

Харьковская, 18-19.10.2026: разлив подписи «ГАЗОН» уходил через разрыв борта на асфальт
пятном, и в 3D край газона и плитки шёл волнами поперёк нарисованных линий. Для показа
каждая грань между линиями (разрывы до 2 м закрыты перемычками) отдаётся материалу, которого
в ней явное большинство; неизвестное остаётся неизвестным, спорная грань - как есть.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from shapely.geometry import LineString, box

from green.application.surfaces import Material, build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel

if TYPE_CHECKING:
    import numpy as np

EXTENT = box(0, 0, 100, 60)


def _curb(i: int, coords: list[tuple[float, float]]) -> Feature:
    return Feature(
        SourceRef("12345678", "00000000", f"C{i}"),
        "Бортовой камень",
        LineString(coords),
        object_class=ObjectClass.CURB,
    )


def _label(i: int, x: float, y: float, text: str) -> TextLabel:
    return TextLabel(SourceRef("12345678", "00000000", f"L{i}"), "Подписи", x, y, text)


def _at(surface, grid: np.ndarray, x: float, y: float) -> int:  # noqa: ANN001 - SurfaceMap
    col = int((x - surface.origin[0]) / surface.cell)
    row = int((y - surface.origin[1]) / surface.cell)
    return int(grid[row, col])


# Газон 20 x 20 м в бортах, в правом борту разрыв 1,2 м.
SQUARE = [
    _curb(1, [(40, 20), (60, 20)]),
    _curb(2, [(60, 20), (60, 29.4)]),
    _curb(3, [(60, 30.6), (60, 40)]),
    _curb(4, [(60, 40), (40, 40)]),
    _curb(5, [(40, 40), (40, 20)]),
]


def test_lawn_leaking_through_a_curb_gap_stays_inside_on_display() -> None:
    labels = [_label(1, 50, 30, "ГАЗОН"), _label(2, 75, 30, "А")]
    surface = build_surface_map(SQUARE, labels, EXTENT, 0.5, inference_mode="hybrid")
    assert surface is not None
    assert surface.display_grid is not None
    # Контроль: разлив действительно проходит через разрыв.
    assert _at(surface, surface.grid, 61.5, 30) == Material.SOIL
    assert _at(surface, surface.display_grid, 61.5, 30) == Material.PAVED
    assert _at(surface, surface.display_grid, 55, 30) == Material.SOIL
    assert _at(surface, surface.display_grid, 59.75, 30) == Material.SOIL


def test_unknown_ground_is_not_invented_on_display() -> None:
    labels = [_label(1, 50, 30, "ГАЗОН"), _label(2, 75, 30, "А")]
    surface = build_surface_map(SQUARE, labels, EXTENT, 0.5, inference_mode="hybrid")
    assert surface is not None
    assert surface.display_grid is not None
    unknown = surface.grid == Material.UNKNOWN
    assert unknown.any()
    assert (surface.display_grid[unknown] == Material.UNKNOWN).all()


def test_face_with_two_real_materials_is_left_as_drawn() -> None:
    # Открытая полоса между двумя бортами: газон и асфальт подписаны поровну.
    strip = [_curb(1, [(0, 20), (100, 20)]), _curb(2, [(0, 30), (100, 30)])]
    labels = [_label(1, 20, 25, "ГАЗОН"), _label(2, 60, 25, "А")]
    surface = build_surface_map(strip, labels, EXTENT, 0.5, inference_mode="hybrid")
    assert surface is not None
    assert surface.display_grid is not None
    assert _at(surface, surface.display_grid, 25, 25) == Material.SOIL
    assert _at(surface, surface.display_grid, 55, 25) == Material.PAVED


def test_display_fills_a_closed_face_where_the_label_spread_stopped() -> None:
    """Кустанайская, 19.10.2026: проезд между двумя бортами, куда «А» дотекала ромбом на
    пределе разлива, выходил с зубцами. В карте для показа замкнутая линиями и в основном
    известная грань заливается материалом целиком."""
    lower = LineString([(0, 0), (50, 0)])
    upper = LineString([(0, 6), (50, 6)])
    ends = [LineString([(0, 0), (0, 6)]), LineString([(50, 0), (50, 6)])]
    features = [
        Feature(
            SourceRef("12345678", "00000000", f"K{i}"), f"curb{i}", g, object_class=ObjectClass.CURB
        )
        for i, g in enumerate([lower, upper, *ends])
    ]
    labels = [TextLabel(SourceRef("12345678", "00000000", "LA"), "Подписи", 5.0, 3.0, "А")]
    surface = build_surface_map(
        features,
        labels,
        box(-10, -10, 60, 16),
        0.5,
        max_distance_m=30.0,
        inference_mode="distance",
    )
    assert surface is not None
    assert surface.display_grid is not None

    def material(grid: object, x: float, y: float) -> int:
        col = int((x - surface.origin[0]) / surface.cell)
        row = int((y - surface.origin[1]) / surface.cell)
        return int(grid[row, col])  # type: ignore[index]

    assert material(surface.grid, 45, 3) != int(Material.PAVED)
    assert material(surface.display_grid, 45, 3) == int(Material.PAVED)


def test_planting_map_does_not_leak_through_a_dashed_curb() -> None:
    """Кустанайская, 19.10.2026: борт съёмки - пунктир из штрихов по метру с просветами по
    полметра; подпись «А» разливалась сквозь просветы за борт. Просветы пунктира закрыты и в
    карте для посадок, а проход шире STROKE_GAP_M остаётся открытым."""
    strokes = [LineString([(1.5 * k, 10), (1.5 * k + 1.0, 10)]) for k in range(27)]
    features = [
        Feature(
            SourceRef("12345678", "00000000", f"D{i}"), "curb", g, object_class=ObjectClass.CURB
        )
        for i, g in enumerate(strokes)
    ]
    labels = [TextLabel(SourceRef("12345678", "00000000", "LA"), "Подписи", 20.0, 5.0, "А")]
    surface = build_surface_map(
        features, labels, box(0, 0, 40, 20), 0.25, max_distance_m=30.0, inference_mode="distance"
    )
    assert surface is not None
    col = int((20 - surface.origin[0]) / surface.cell)
    above = int((15 - surface.origin[1]) / surface.cell)
    below = int((5 - surface.origin[1]) / surface.cell)
    assert int(surface.grid[below, col]) == int(Material.PAVED)
    assert int(surface.grid[above, col]) != int(Material.PAVED)


def test_paving_runs_under_a_dashed_canopy_but_not_into_a_house() -> None:
    """Кустанайская, 19.10.2026: навес посреди детской площадки (пунктир слоя «Навесы»)
    останавливал разлив «СПЕЦ.ПОКР.», и под ним в 3D рос газон. Пунктир здания - над землёй,
    покрытие идёт под него; сплошной контур дома разлив по-прежнему не пускает."""
    ring = LineString([(45, 25), (52, 25), (52, 33), (45, 33), (45, 25)])

    def house(*, dashed: bool) -> Feature:
        return Feature(
            SourceRef("12345678", "00000000", "H1"),
            "Навесы",
            ring,
            object_class=ObjectClass.BUILDING,
            dashed=dashed,
        )

    labels = [_label(1, 42, 22, "А")]
    for dashed, expected in ((True, True), (False, False)):
        features = [*SQUARE[:2], _curb(9, [(60, 29), (60, 31)]), *SQUARE[2:], house(dashed=dashed)]
        surface = build_surface_map(features, labels, EXTENT, 0.5, inference_mode="hybrid")
        assert surface is not None
        assert (_at(surface, surface.grid, 48.5, 29) == Material.PAVED) is expected


def test_labelled_lawn_by_an_open_driveway_is_not_painted_over() -> None:
    """Кустанайская, 19.10.2026: газон с подписью «ГАЗОН» и деревьями открыт к асфальту двора
    (между ними нет линии), и в грани для показа он был меньшинством - его красили асфальтом,
    деревья стояли на асфальте. Меньшинство со своей подписью в грани остаётся."""
    strip = [_curb(1, [(0, 20), (100, 20)]), _curb(2, [(0, 30), (100, 30)])]
    labels = [_label(i, x, 25, "А") for i, x in enumerate((10, 30, 50, 70))]
    labels.append(_label(9, 95, 25, "ГАЗОН"))
    surface = build_surface_map(strip, labels, EXTENT, 0.5, inference_mode="hybrid")
    assert surface is not None
    assert surface.display_grid is not None
    assert _at(surface, surface.grid, 95, 25) == Material.SOIL
    assert _at(surface, surface.display_grid, 95, 25) == Material.SOIL
    assert _at(surface, surface.display_grid, 30, 25) == Material.PAVED


def test_label_on_a_line_paints_the_narrow_walk_on_display_only() -> None:
    """Кустанайская, 19.10.2026: «А» узкого тротуара между бортом и оградой стоит точкой
    вставки на двойной линии знака ограды и не разливалась - тротуар в 3D был газоном. В
    карте для показа такая подпись сдвигается в ближайшую свободную клетку; в карте для
    посадок сторону не выбирает."""
    walk = [
        _curb(1, [(0, 20), (100, 20)]),
        _curb(2, [(0, 22), (100, 22)]),
        _curb(3, [(0, 22.5), (100, 22.5)]),
    ]
    labels = [_label(1, 50, 22.25, "А")]  # точка вставки между линиями знака ограды
    planting = build_surface_map(walk, labels, EXTENT, 0.5, inference_mode="hybrid")
    assert planting is not None
    assert _at(planting, planting.grid, 50, 21) == Material.UNKNOWN
    display = build_surface_map(
        walk,
        labels,
        box(-10, -10, 110, 70),
        0.5,
        inference_mode="hybrid",
        display_around=EXTENT,
    )
    assert display is not None
    assert _at(display, display.grid, 50, 21) == Material.PAVED
