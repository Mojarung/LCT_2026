"""Профиль отключает правила: охранные зоны поверх отступов табл. 9.1 не применяются.

Ответ заказчика на сессии вопросов 17.09.2026 (docs/notes/15-organizers-qa.md, вопрос 8).
Точка в 1,8 м от оси газопровода: по табл. 9.1 СП 42 (1,5 м до стенки трубы) посадка
допустима, в охранной зоне (ПП РФ N 878, п. 7 «а», 8, 16) - только по письменному разрешению
эксплуатационной организации: яма глубже 0,3 м.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import shapely
from shapely.geometry import LineString

from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams, active_distance_rules
from green.application.placement import disabled_rules_note
from green.domain.norms import PlantingType
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Verdict
from green.infrastructure.config.repositories import YamlProfileSource, YamlRuleBookSource

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
GAS_ZONE = "R-GASZONE-TREE-001"
GAS_ZONE_SHRUB = "R-GASZONE-SHRUB-001"
ZONE_M = 2.0  # ПП РФ N 878, п. 7 «а»: 2 м с каждой стороны газопровода


def _gas_pipe() -> Feature:
    return Feature(
        ref=SourceRef(file_sha8="0" * 8, xref_hash8="0" * 8, handle="1"),
        layer="Газопровод",
        geometry=LineString([(0, 0), (100, 0)]),
        object_class=ObjectClass.UTILITY_GAS,
    )


def _verdict(params: PlanParams, y: float = 1.8) -> Verdict:
    rules = active_distance_rules(RULEBOOK, params)
    index = ConstraintIndex([_gas_pipe()], rules, require_utility_data=True)
    batch = index.evaluate(shapely.points([(50.0, y)]))
    return batch.verdict(0)


def test_gas_protective_zone_is_off_in_the_shipped_profiles() -> None:
    profiles = YamlProfileSource(CONFIG / "profiles")
    for name in profiles.names():
        assert {GAS_ZONE, GAS_ZONE_SHRUB} <= set(profiles.load(name).disabled_rules), name


def test_disabled_rule_is_not_evaluated() -> None:
    enabled = PlanParams()
    disabled = replace(enabled, disabled_rules=(GAS_ZONE,))
    assert GAS_ZONE in {r.rule_id for r in active_distance_rules(RULEBOOK, enabled)}
    assert GAS_ZONE not in {r.rule_id for r in active_distance_rules(RULEBOOK, disabled)}
    assert _verdict(enabled) is Verdict.NEEDS_APPROVAL
    assert _verdict(disabled) is Verdict.ALLOWED


def test_table_distance_to_gas_still_applies_when_the_zone_is_off() -> None:
    disabled = replace(PlanParams(), disabled_rules=(GAS_ZONE,))
    rules = active_distance_rules(RULEBOOK, disabled)
    index = ConstraintIndex([_gas_pipe()], rules, require_utility_data=True)
    assert index.evaluate(shapely.points([(50.0, 1.2)])).verdict(0) is Verdict.FORBIDDEN


def test_the_warning_names_the_disabled_rule_by_its_clause() -> None:
    """Эксперт читает пункт акта, а не идентификатор: номер правила - в параметрах прогона."""
    note = disabled_rules_note(RULEBOOK, replace(PlanParams(), disabled_rules=(GAS_ZONE,)))
    assert note is not None
    assert "охранная зона" in note
    assert "газопровода" in note
    assert GAS_ZONE not in note
    assert disabled_rules_note(RULEBOOK, PlanParams()) is None


def test_gas_zone_is_measured_to_the_pit_not_to_the_trunk() -> None:
    """П. 16 ограничивает нарушение почвы глубже 0,3 м: в зону не должна заходить яма, поэтому
    порог - 2 м плюс радиус посадочного места дерева или куста."""
    params = PlanParams()
    rules = {r.rule_id: r for r in RULEBOOK.distance_rules}
    assert rules[GAS_ZONE].min_distance_m == ZONE_M + params.planting_radius_m
    assert rules[GAS_ZONE_SHRUB].min_distance_m == ZONE_M + params.shrub_planting_radius_m


def test_inside_the_gas_zone_a_planting_needs_approval_beyond_it_is_allowed() -> None:
    tree = PlanParams()
    shrub = replace(tree, planting_type=PlantingType.SHRUB)
    edge_tree = ZONE_M + tree.planting_radius_m
    edge_shrub = ZONE_M + tree.shrub_planting_radius_m

    assert _verdict(tree, 1.2) is Verdict.FORBIDDEN  # табл. 9.1 СП 42: ближе 1,5 м
    assert _verdict(tree, edge_tree - 0.2) is Verdict.NEEDS_APPROVAL
    assert _verdict(tree, edge_tree + 0.2) is Verdict.ALLOWED
    assert _verdict(shrub, edge_shrub - 0.2) is Verdict.NEEDS_APPROVAL
    assert _verdict(shrub, edge_shrub + 0.2) is Verdict.ALLOWED
