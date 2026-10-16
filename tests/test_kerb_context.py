"""Борт у тротуара - край тротуара (0,7 / 0,5 м), борт у проезжей части - край проезжей части.

Аудит Берзарина 16.10.2026 (docs/research/jury-audit-2026-10-16/remaining_discrepancies_review.md,
п. 2): из 128 срабатываний по борту 104 - борта тротуара в метрах от проектной проезжей части,
а сервис требовал 2 м, как от края проезжей части. СП 42.13330.2016, табл. 9.1: «край
проезжей части улиц» 2,0 / 1,0; «край тротуара и садовой дорожки» 0,7 / 0,5.

Схема: проезжая часть y 0..10 (100 м вдоль), борт проезжей части по y = 10, тротуар y 10..13,
борт тротуара по y = 13 (между тротуаром и газоном), газон выше.
"""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, box

from green.application.kerbs import refine_kerbs
from green.domain.objects import Feature, ObjectClass, SourceRef

C = ObjectClass


def _f(handle: str, cls: ObjectClass, geometry: object) -> Feature:
    return Feature(SourceRef("f", "x", handle), f"layer-{handle}", geometry, object_class=cls)


ROAD = _f("R", C.ROAD, box(0, 0, 100, 10))
WALK = _f("W", C.SIDEWALK, box(0, 10, 100, 13))
ROAD_KERB = _f("K1", C.CURB, LineString([(0, 10), (100, 10)]))
WALK_KERB = _f("K2", C.CURB, LineString([(0, 13), (100, 13)]))


def _classes(features: tuple[Feature, ...], handle: str) -> dict[ObjectClass, float]:
    out: dict[ObjectClass, float] = {}
    for f in features:
        if f.ref.handle == handle:
            out[f.object_class] = out.get(f.object_class, 0.0) + f.geometry.length
    return out


def test_kerb_between_footway_and_lawn_is_the_footway_edge() -> None:
    refined, _ = refine_kerbs((ROAD, WALK, ROAD_KERB, WALK_KERB))
    assert _classes(refined, "K2") == {C.PAVEMENT_EDGE: pytest.approx(100.0)}
    (edge,) = (f for f in refined if f.ref.handle == "K2")
    assert edge.classification is not None
    assert edge.classification.method == "context:kerb_beside_footway"


def test_kerb_on_the_carriageway_edge_stays_a_carriageway_kerb() -> None:
    refined, _ = refine_kerbs((ROAD, WALK, ROAD_KERB, WALK_KERB))
    assert _classes(refined, "K1") == {C.CURB: pytest.approx(100.0)}


def test_kerb_partly_beside_the_road_is_split_by_length() -> None:
    """Борт идёт вдоль тротуара, а последние 20 м - по краю проезжей части (заезд)."""
    bent = _f("K3", C.CURB, LineString([(0, 13), (80, 13), (80, 10), (100, 10)]))
    refined, _ = refine_kerbs((ROAD, WALK, ROAD_KERB, bent))
    parts = _classes(refined, "K3")
    # 20 м по краю проезжей части и метр спуска у дороги
    assert parts[C.CURB] == pytest.approx(20.0 + 1.0, abs=0.1)
    assert parts[C.PAVEMENT_EDGE] == pytest.approx(80.0 + 2.0, abs=0.1)


def test_kerb_with_no_footway_beside_it_stays_a_carriageway_kerb() -> None:
    """Review Focus 1: в сомнении борт остаётся краем проезжей части - норма не ослабляется."""
    far = _f("K4", C.CURB, LineString([(0, 40), (100, 40)]))
    refined, _ = refine_kerbs((ROAD, WALK, ROAD_KERB, far))
    assert _classes(refined, "K4") == {C.CURB: pytest.approx(100.0)}


def test_without_carriageway_polygons_nothing_changes_and_the_report_says_why() -> None:
    """Review Focus 2: улица без полигонов проезжей части - все борта как раньше."""
    features = (WALK, ROAD_KERB, WALK_KERB)
    refined, note = refine_kerbs(features)
    assert refined == features
    assert note is not None
    assert "проезжей части" in note


def test_partial_carriageway_polygons_change_nothing() -> None:
    """Полигоны - участки ремонта (вдоль них меньше половины бортов): борт у тротуара вдали
    от такого участка может стоять у ненарисованной проезжей части."""
    patch = _f("R", C.ROAD, box(0, 0, 10, 10))
    extra = tuple(_f(f"E{i}", C.CURB, LineString([(0, 50 + i), (100, 50 + i)])) for i in range(3))
    features = (patch, WALK, ROAD_KERB, WALK_KERB, *extra)
    refined, note = refine_kerbs(features)
    assert refined == features
    assert note is not None
