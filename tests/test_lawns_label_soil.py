"""Газон на грунте, разлитом от подписи (совмещённый режим карты покрытий).

Съёмка Мосгеотреста редко замыкает газон: на 7 из 19 улиц пилота весь грунт карты покрытий -
разлив от подписей «ГАЗОН», и до 18.10.2026 газонов плана там не было вовсе (п. 3 ТЗ,
травянистые покрытия), хотя деревья на том же грунте сажались. Газон по разливу выделяется
с заметкой, что граница приблизительная.
"""

from __future__ import annotations

from dataclasses import replace

from shapely.geometry import LineString, box
from test_pipeline_synthetic import ROOT

from green.application.constraints import work_boundary
from green.application.lawns import WARNING_PREFIX, plan_lawns
from green.application.params import PlanParams
from green.application.surfaces import build_surface_map
from green.domain.norms import LawnKind
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel
from green.domain.planting import Plan
from green.infrastructure.config.repositories import YamlRuleBookSource

BOOK = YamlRuleBookSource(ROOT / "config" / "acts.yaml", ROOT / "config" / "rules.yaml").load()
EXTENT = box(0, 0, 100, 60)


def _feature(cls: ObjectClass, geometry: object, name: str) -> Feature:
    return Feature(SourceRef("12345678", "00000000", name), name, geometry, object_class=cls)  # type: ignore[arg-type]


def _label(i: int, x: float, y: float, text: str) -> TextLabel:
    return TextLabel(SourceRef("12345678", "00000000", f"L{i}"), "Подписи", x, y, text)


# Полоса между двумя бортами, концы открыты: грань не замыкается, грунт только разливом.
FEATURES = [
    _feature(ObjectClass.CURB, LineString([(0, 20), (100, 20)]), "c1"),
    _feature(ObjectClass.CURB, LineString([(0, 30), (100, 30)]), "c2"),
    _feature(ObjectClass.WORK_BOUNDARY, EXTENT, "boundary"),
]


def _plan(text: str, mode: str = "hybrid") -> Plan:
    labels = [_label(1, 50, 25, text)]
    surface = build_surface_map(FEATURES, labels, work_boundary(FEATURES), 0.5, inference_mode=mode)
    assert surface is not None
    return plan_lawns(
        Plan(placements=(), rejections=()),
        features=FEATURES,
        labels=labels,
        surface=surface,
        rulebook=BOOK,
        params=PlanParams(),
    )


def test_lawn_label_spread_becomes_a_kept_lawn_with_an_approximate_border() -> None:
    plan = _plan("ГАЗОН")

    assert {lawn.kind for lawn in plan.lawns} == {LawnKind.KEPT}
    area = sum(lawn.area_m2 for lawn in plan.lawns)
    # Разлив - 30 м в обе стороны от подписи по полосе шириной 10 м, без клеток у бортов.
    assert 500 < area < 620
    assert all(box(19, 19.5, 81, 30.5).covers(lawn.geometry) for lawn in plan.lawns)
    assert all(any("по близости подписи" in note for note in lawn.notes) for lawn in plan.lawns)
    assert plan.stats["lawn_label_m2"] == round(area, 1)


def test_ground_label_spread_becomes_a_new_lawn() -> None:
    plan = _plan("ГРУНТ")

    assert plan.lawns
    assert {lawn.kind for lawn in plan.lawns} == {LawnKind.NEW}


def test_flowerbed_label_spread_is_kept_out_of_the_lawn() -> None:
    plan = _plan("ЦВЕТНИК")

    assert not plan.lawns
    assert any(w.startswith(WARNING_PREFIX) and "цветники по чертежу" in w for w in plan.warnings)


def test_strict_mode_has_no_spread_and_no_lawn() -> None:
    plan = _plan("ГАЗОН", mode="closed_faces")

    assert not plan.lawns
    assert plan.stats.get("lawn_label_m2", 0) == 0


def test_soil_touching_the_work_boundary_from_outside_keeps_the_lawn_kept() -> None:
    """Куликовская 18.10.2026: газон за границей работ касается её ребром, пересечение с
    границей - коллекция с линией, а у коллекции нет границы: грани грунта не строились, и
    газон разлива подписи «ГАЗОН» уходил в устраиваемый."""
    # Обрывок борта внутри полосы: грани строятся из линий и границы грунта.
    features = [*FEATURES, _feature(ObjectClass.CURB, LineString([(60, 22), (60, 28)]), "d")]
    labels = [_label(1, 50, 25, "ГАЗОН")]
    surface = build_surface_map(
        features, labels, work_boundary(features), 0.5, inference_mode="hybrid"
    )
    assert surface is not None
    surface = replace(surface, soil_area=box(100, 0, 110, 60))
    plan = plan_lawns(
        Plan(placements=(), rejections=()),
        features=features,
        labels=labels,
        surface=surface,
        rulebook=BOOK,
        params=PlanParams(),
    )

    assert plan.lawns
    assert {lawn.kind for lawn in plan.lawns} == {LawnKind.KEPT}
