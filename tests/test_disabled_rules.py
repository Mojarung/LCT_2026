"""Профиль отключает правила: охранные зоны поверх отступов табл. 9.1 не применяются.

Ответ заказчика на сессии вопросов 17.09.2026 (docs/notes/15-organizers-qa.md, вопрос 8).
Точка в 1,8 м от оси газопровода: по табл. 9.1 СП 42 (1,5 м до стенки трубы) посадка
допустима, по охранной зоне 2 м от оси (R-GASZONE-TREE-001) нет.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import shapely
from shapely.geometry import LineString

from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams, active_distance_rules
from green.application.placement import disabled_rules_note
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Verdict
from green.infrastructure.config.repositories import YamlProfileSource, YamlRuleBookSource

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
GAS_ZONE = "R-GASZONE-TREE-001"


def _gas_pipe() -> Feature:
    return Feature(
        ref=SourceRef(file_sha8="0" * 8, xref_hash8="0" * 8, handle="1"),
        layer="Газопровод",
        geometry=LineString([(0, 0), (100, 0)]),
        object_class=ObjectClass.UTILITY_GAS,
    )


def _verdict(params: PlanParams) -> Verdict:
    rules = active_distance_rules(RULEBOOK, params)
    index = ConstraintIndex([_gas_pipe()], rules, require_utility_data=True)
    batch = index.evaluate(shapely.points([(50.0, 1.8)]))
    return batch.verdict(0)


def test_gas_protective_zone_is_off_in_the_shipped_profiles() -> None:
    profiles = YamlProfileSource(CONFIG / "profiles")
    for name in profiles.names():
        assert GAS_ZONE in profiles.load(name).disabled_rules, name


def test_disabled_rule_is_not_evaluated() -> None:
    enabled = PlanParams()
    disabled = replace(enabled, disabled_rules=(GAS_ZONE,))
    assert GAS_ZONE in {r.rule_id for r in active_distance_rules(RULEBOOK, enabled)}
    assert GAS_ZONE not in {r.rule_id for r in active_distance_rules(RULEBOOK, disabled)}
    assert _verdict(enabled) is Verdict.FORBIDDEN
    assert _verdict(disabled) is Verdict.ALLOWED


def test_table_distance_to_gas_still_applies_when_the_zone_is_off() -> None:
    disabled = replace(PlanParams(), disabled_rules=(GAS_ZONE,))
    rules = active_distance_rules(RULEBOOK, disabled)
    index = ConstraintIndex([_gas_pipe()], rules, require_utility_data=True)
    assert index.evaluate(shapely.points([(50.0, 1.2)])).verdict(0) is Verdict.FORBIDDEN


def test_the_warning_names_the_disabled_rule_by_its_clause() -> None:
    """Эксперт читает пункт акта, а не идентификатор: номер остаётся в скобках для трассы."""
    note = disabled_rules_note(RULEBOOK, replace(PlanParams(), disabled_rules=(GAS_ZONE,)))
    assert note is not None
    assert "охранная зона газопровода" in note
    assert note.endswith(f"({GAS_ZONE}).")
    assert disabled_rules_note(RULEBOOK, PlanParams()) is None
