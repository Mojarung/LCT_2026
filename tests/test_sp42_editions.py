"""Редакции СП 42.13330: 2016 названа в ТЗ, 2026 действует с 12.07.2026.

Таблица расстояний до деревьев переехала из табл. 9.1 (п. 9.6) в табл. 6.3 (п. 6.4.8); значения
разошлись в двух строках: силовой кабель у кустарника 0,75 м вместо 0,7, кабель связи - по
РД 45.120-2000 (1,5 м до ствола, кустарник не нормирован) вместо 2,0 / 0,7.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import shapely
from shapely.geometry import LineString

from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams, active_distance_rules
from green.domain.norms import PlantingType
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Verdict
from green.infrastructure.config.repositories import YamlProfileSource, YamlRuleBookSource

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()


def _cable(object_class: ObjectClass) -> Feature:
    return Feature(
        ref=SourceRef(file_sha8="0" * 8, xref_hash8="0" * 8, handle="1"),
        layer="Кабель",
        geometry=LineString([(0, 0), (100, 0)]),
        object_class=object_class,
    )


def _verdict(edition: str, kind: PlantingType, cable: ObjectClass, y: float) -> Verdict:
    params = replace(PlanParams(), planting_type=kind, sp42_edition=edition)
    rules = active_distance_rules(RULEBOOK.for_sp42_edition(edition), params)
    index = ConstraintIndex([_cable(cable)], rules, require_utility_data=True)
    return index.evaluate(shapely.points([(50.0, y)])).verdict(0)


def test_each_edition_keeps_its_own_rows_and_all_common_rules() -> None:
    old = {r.rule_id: r for r in RULEBOOK.for_sp42_edition("2016").distance_rules}
    new = {r.rule_id: r for r in RULEBOOK.for_sp42_edition("2026").distance_rules}

    assert old["R-POWER-SHRUB-001"].min_distance_m == 0.7
    assert new["R-POWER-SHRUB-002"].min_distance_m == 0.75
    assert new["R-TELECOM-TREE-002"].min_distance_m == 1.5
    assert {"R-POWER-SHRUB-002", "R-TELECOM-TREE-002"}.isdisjoint(old)
    assert {"R-POWER-SHRUB-001", "R-TELECOM-TREE-001", "R-TELECOM-SHRUB-001"}.isdisjoint(new)
    assert set(old) - {"R-POWER-SHRUB-001", "R-TELECOM-TREE-001", "R-TELECOM-SHRUB-001"} == set(
        new
    ) - {"R-POWER-SHRUB-002", "R-TELECOM-TREE-002"}


def test_every_table_rule_names_its_row_in_the_2026_edition() -> None:
    """Эксперт, знающий действующую редакцию, находит тот же пункт: 6.4.8, табл. 6.3."""
    for rule in RULEBOOK.distance_rules:
        if rule.citation.act_id == "SP42_13330_2016" and "табл. 9.1" in rule.citation.clause:
            related = [r for r in rule.citation.related if r.act_id == "SP42_13330_2026"]
            assert related, rule.rule_id
            assert "табл. 6.3" in related[0].clause, rule.rule_id


def test_the_editions_differ_exactly_where_the_tables_do() -> None:
    tree, shrub = PlantingType.TREE, PlantingType.SHRUB
    telecom, power = ObjectClass.UTILITY_TELECOM, ObjectClass.UTILITY_POWER
    # Дерево в 1,8 м от кабеля связи: ред. 2016 - 2,0 м, ред. 2026 (РД 45.120-2000) - 1,5 м.
    assert _verdict("2016", tree, telecom, 1.8) is Verdict.FORBIDDEN
    assert _verdict("2026", tree, telecom, 1.8) is Verdict.ALLOWED
    # Куст в 0,72 м от силового кабеля: 0,7 м в ред. 2016, 0,75 м в ред. 2026.
    assert _verdict("2016", shrub, power, 0.72) is Verdict.ALLOWED
    assert _verdict("2026", shrub, power, 0.72) is Verdict.FORBIDDEN
    # Куст у кабеля связи: 0,7 м в ред. 2016, в ред. 2026 норма не установлена.
    assert _verdict("2016", shrub, telecom, 0.5) is Verdict.FORBIDDEN
    assert _verdict("2026", shrub, telecom, 0.5) is Verdict.ALLOWED


def test_profiles_follow_the_brief_and_name_2016_by_default() -> None:
    profiles = YamlProfileSource(CONFIG / "profiles")
    for name in profiles.names():
        assert profiles.load(name).sp42_edition == "2016", name


def test_the_edition_is_accepted_as_a_year_number_from_the_command_line() -> None:
    """--set sp42_edition=2026 разбирается как YAML в число, JSON в интерфейсе - тоже."""
    profiles = YamlProfileSource(CONFIG / "profiles")

    assert profiles.load("strict", {"sp42_edition": 2026}).sp42_edition == "2026"
    assert profiles.load("strict", {"sp42_edition": "2016"}).sp42_edition == "2016"
