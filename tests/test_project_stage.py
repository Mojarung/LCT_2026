"""Старая граница покрытия внутри проектного газона не ограничивает посадку.

Аудит Берзарина 16.10.2026 (remaining_discrepancies_review.md, п. 3): у 48 из 49 срабатываний
«край тротуара» граница топосъёмки лежала внутри объединённого проектного газона - проект
заменил покрытие газоном, а линия съёмки осталась. Соседние штриховки газона объединяются:
их общая граница - внутренняя линия одного газона.
"""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, box

from green.application.project_stage import drop_edges_inside_lawn
from green.domain.objects import Feature, ObjectClass, SourceRef

C = ObjectClass


def _f(handle: str, cls: ObjectClass, geometry: object) -> Feature:
    return Feature(SourceRef("f", "x", handle), f"layer-{handle}", geometry, object_class=cls)


LAWN_A = _f("A", C.LAWN, box(0, 0, 10, 10))
LAWN_B = _f("B", C.LAWN, box(10, 0, 20, 10))  # смежная штриховка того же газона
WALK = _f("W", C.SIDEWALK, box(0, 10, 20, 13))


def _length(features: tuple[Feature, ...], handle: str, cls: ObjectClass) -> float:
    return sum(
        f.geometry.length for f in features if f.ref.handle == handle and f.object_class is cls
    )


def test_survey_edge_inside_the_merged_lawn_is_dropped() -> None:
    old = _f("E", C.PAVEMENT_EDGE, LineString([(2, 5), (18, 5)]))  # пересекает стык A|B
    refined, dropped = drop_edges_inside_lawn((LAWN_A, LAWN_B, WALK, old))
    assert _length(refined, "E", C.PAVEMENT_EDGE) == 0
    assert dropped == 1


def test_edge_between_lawn_and_footway_stays() -> None:
    edge = _f("E", C.PAVEMENT_EDGE, LineString([(0, 10), (20, 10)]))
    refined, dropped = drop_edges_inside_lawn((LAWN_A, LAWN_B, WALK, edge))
    assert _length(refined, "E", C.PAVEMENT_EDGE) == pytest.approx(20.0)
    assert dropped == 0


def test_edge_leaving_the_lawn_keeps_its_outside_part() -> None:
    edge = _f("E", C.PAVEMENT_EDGE, LineString([(5, 5), (5, 20)]))  # 5 м в газоне, дальше снаружи
    refined, _ = drop_edges_inside_lawn((LAWN_A, LAWN_B, WALK, edge))
    assert _length(refined, "E", C.PAVEMENT_EDGE) == pytest.approx(10.0 + 0.15, abs=0.01)


def test_kerb_inside_a_lawn_is_not_touched() -> None:
    """Только граница покрытия: борт внутри газона (садовый борт клумбы) остаётся."""
    kerb = _f("K", C.CURB, LineString([(2, 5), (8, 5)]))
    refined, dropped = drop_edges_inside_lawn((LAWN_A, kerb))
    assert _length(refined, "K", C.CURB) == pytest.approx(6.0)
    assert dropped == 0


def test_dropped_part_stays_visible_with_its_reason() -> None:
    """Ревью 16.10.2026: пересмотр класса виден в classification.json с основанием."""
    old = _f("E", C.PAVEMENT_EDGE, LineString([(2, 5), (18, 5)]))
    refined, _ = drop_edges_inside_lawn((LAWN_A, LAWN_B, WALK, old))
    ignored = [f for f in refined if f.ref.handle == "E" and f.object_class is C.IGNORE]
    assert ignored
    assert ignored[0].classification is not None
    assert ignored[0].classification.method == "context:inside_project_lawn"
