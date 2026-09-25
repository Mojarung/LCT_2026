"""Совмещённый режим карты покрытий (вопрос 3 пользователя, 25.09.2026, вариант 1).

Съёмка Мосгеотреста редко замыкает газон целиком: на Кустанайской 32 958 открытых рёбер, и ни
одна из 1030 подписей не попала в замкнутую грань - строгий режим дал 0 посадок. Совмещённый
режим: замкнутая грань решает сама; подпись вне решённой грани разливает материал по
расстоянию (до 30 м, через границы не переходит, «ГАЗОН» конкурирует с «А»); решённая грань
не переписывается, существующее дерево грунта не создаёт.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import LineString, Point, box

from green.application.surfaces import Material, build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel

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


def _material(surface, x: float, y: float) -> int:  # noqa: ANN001 - SurfaceMap
    return int(surface.material(np.array([Point(x, y)], dtype=object))[0])


# Полоса газона между двумя бортами, концы полосы открыты: грань не замыкается.
STRIP = [_curb(1, [(0, 20), (100, 20)]), _curb(2, [(0, 30), (100, 30)])]


def test_open_lawn_strip_is_soil_by_its_label_in_hybrid_mode_only() -> None:
    labels = [_label(1, 50, 25, "ГАЗОН")]
    strict = build_surface_map(STRIP, labels, EXTENT, 0.5, inference_mode="closed_faces")
    hybrid = build_surface_map(STRIP, labels, EXTENT, 0.5, inference_mode="hybrid")
    assert strict is not None
    assert hybrid is not None
    assert _material(strict, 60, 25) != Material.SOIL
    assert _material(hybrid, 60, 25) == Material.SOIL
    # Разлив не переходит через борт и не уходит дальше 30 м от подписи.
    assert _material(hybrid, 60, 35) != Material.SOIL
    assert _material(hybrid, 95, 25) != Material.SOIL
    assert hybrid.fits_soil(np.array([Point(60, 25)], dtype=object), 1.6)[0]
    assert any("по близости подписи" in note for note in hybrid.review_notes())


def test_lawn_and_asphalt_labels_compete_in_one_open_strip() -> None:
    labels = [_label(1, 20, 25, "ГАЗОН"), _label(2, 60, 25, "А")]
    hybrid = build_surface_map(STRIP, labels, EXTENT, 0.5, inference_mode="hybrid")
    assert hybrid is not None
    assert _material(hybrid, 25, 25) == Material.SOIL
    assert _material(hybrid, 55, 25) == Material.PAVED
    assert _material(hybrid, 40, 25) == Material.UNKNOWN  # ровно посередине - спорно


def test_decided_closed_face_is_not_overwritten_by_a_label_outside() -> None:
    square = [
        _curb(3, [(60, 35), (80, 35)]),
        _curb(4, [(80, 35), (80, 55)]),
        _curb(5, [(80, 55), (60, 55)]),
        _curb(6, [(60, 55), (60, 35)]),
    ]
    labels = [_label(1, 70, 45, "А"), _label(2, 55, 45, "ГАЗОН")]
    hybrid = build_surface_map(square, labels, EXTENT, 0.5, inference_mode="hybrid")
    assert hybrid is not None
    assert _material(hybrid, 75, 50) == Material.PAVED
    assert _material(hybrid, 50, 45) == Material.SOIL


def test_existing_tree_does_not_create_soil_in_hybrid_mode() -> None:
    """Дерево в решётке на тротуаре не открывает тротуар под посадку."""
    tree = Feature(
        SourceRef("12345678", "00000000", "T1"),
        "Отдельно стоящее дерево",
        Point(50, 25),
        object_class=ObjectClass.EXISTING_TREE,
    )
    hybrid = build_surface_map([*STRIP, tree], [], EXTENT, 0.5, inference_mode="hybrid")
    assert hybrid is None or _material(hybrid, 50.5, 25) != Material.SOIL
