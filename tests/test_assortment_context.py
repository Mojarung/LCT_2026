"""Контекст точки: расстояния по классам берутся из уже посчитанных проверок правил."""

from __future__ import annotations

from green.application.assortment.context import nearest_clearance, site_context
from green.domain.norms import PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Placement, RuleCheck, Species, Verdict


def _placement(checks: tuple[RuleCheck, ...]) -> Placement:
    return Placement(
        placement_id="p-1",
        number=1,
        planting_type=PlantingType.TREE,
        species=Species("tilia_cordata", "Липа", "Tilia cordata", 4.0),
        x=10.0,
        y=20.0,
        verdict=Verdict.ALLOWED,
        checks=checks,
    )


def test_context_takes_minimum_distance_per_class_and_line_flag() -> None:
    checks = (
        RuleCheck("R-ROAD-TREE-001", CheckOutcome.PASS, 2.0, 3.1, None, ObjectClass.ROAD),
        RuleCheck("R-CURB-TREE-001", CheckOutcome.PASS, 2.0, 2.4, None, ObjectClass.CURB),
        RuleCheck("R-HEAT-TREE-001", CheckOutcome.PASS, 2.0, 2.6, None, ObjectClass.UTILITY_HEAT),
        RuleCheck(
            "R-OHL-TREE-001", CheckOutcome.FAIL, 2.0, 1.1, None, ObjectClass.POWER_LINE_OVERHEAD
        ),
        RuleCheck("R-GAS-TREE-001", CheckOutcome.NO_DATA, 1.5, None, None, ObjectClass.UTILITY_GAS),
    )
    ctx = site_context(_placement(checks))
    assert ctx.placement_id == "p-1"
    assert ctx.clearance_m[ObjectClass.CURB] == 2.4
    assert ObjectClass.UTILITY_GAS not in ctx.clearance_m
    assert ctx.under_overhead_line
    assert nearest_clearance(ctx, (ObjectClass.ROAD, ObjectClass.CURB)) == 2.4
    assert nearest_clearance(ctx, (ObjectClass.BUILDING,)) is None


def test_several_checks_of_one_class_collapse_to_the_nearest() -> None:
    checks = (
        RuleCheck("R-HEAT-TREE-001", CheckOutcome.PASS, 2.0, 5.0, None, ObjectClass.UTILITY_HEAT),
        RuleCheck("R-HEAT-TILIA-001", CheckOutcome.PASS, 2.0, 2.2, None, ObjectClass.UTILITY_HEAT),
    )
    ctx = site_context(_placement(checks))
    assert ctx.clearance_m[ObjectClass.UTILITY_HEAT] == 2.2


def test_line_flag_is_false_when_the_line_is_far_enough() -> None:
    checks = (
        RuleCheck(
            "R-OHL-TREE-001", CheckOutcome.PASS, 2.0, 7.0, None, ObjectClass.POWER_LINE_OVERHEAD
        ),
    )
    ctx = site_context(_placement(checks))
    assert not ctx.under_overhead_line
    assert ctx.clearance_m[ObjectClass.POWER_LINE_OVERHEAD] == 7.0


def test_structure_is_attached_without_recomputing_distances() -> None:
    ctx = site_context(_placement(()), structure_id="row-1", structure_kind="row")
    assert ctx.structure_id == "row-1"
    assert ctx.structure_kind == "row"
    assert ctx.clearance_m == {}
