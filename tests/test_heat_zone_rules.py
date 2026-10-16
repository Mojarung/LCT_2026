"""Охранная зона тепловой сети: Типовые правила охраны коммунальных тепловых сетей (приказ
Минстроя РФ от 17.08.1992 № 197). П. 4: не менее 3 м в каждую сторону от края строительных
конструкций или наружной поверхности изолированного теплопровода. П. 6: посадка деревьев и
кустарников в зоне - только с письменного согласия владельца сети (текст сверен 16.10.2026 по
legalacts.ru). Идея - Sylvitect и LPN1KoL; как у газопровода (ПП РФ № 878), в зону не
заходит яма, а в профилях правило выключено по ответу заказчика (охранные зоны поверх
отступов не применять, notes/15, вопрос 8).
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
TREE_RULE = "R-HEATZONE-TREE-001"
SHRUB_RULE = "R-HEATZONE-SHRUB-001"
ZONE_M = 3.0


def _verdict(params: PlanParams, y: float) -> Verdict:
    pipe = Feature(
        SourceRef("0", "0", "1"),
        "Теплосеть",
        LineString([(0, 0), (100, 0)]),
        object_class=ObjectClass.UTILITY_HEAT,
    )
    index = ConstraintIndex(
        [pipe], active_distance_rules(RULEBOOK, params), require_utility_data=True
    )
    return index.evaluate(shapely.points([(50.0, y)])).verdict(0)


def test_zone_is_three_metres_plus_the_pit_with_the_owner_consent() -> None:
    rules = {r.rule_id: r for r in RULEBOOK.distance_rules}
    params = PlanParams()
    assert rules[TREE_RULE].min_distance_m == ZONE_M + params.planting_radius_m
    assert rules[SHRUB_RULE].min_distance_m == ZONE_M + params.shrub_planting_radius_m
    assert rules[TREE_RULE].citation.act_id == "MINSTROY197"
    assert "письменного согласия" in rules[TREE_RULE].citation.quote


def test_inside_the_zone_a_tree_needs_approval_beyond_it_is_allowed() -> None:
    tree = PlanParams()
    edge = ZONE_M + tree.planting_radius_m
    assert _verdict(tree, edge - 0.3) is Verdict.NEEDS_APPROVAL
    assert _verdict(tree, edge + 0.3) is Verdict.ALLOWED
    shrub = replace(tree, planting_type=PlantingType.SHRUB)
    assert _verdict(shrub, ZONE_M + tree.shrub_planting_radius_m - 0.2) is Verdict.NEEDS_APPROVAL


def test_heat_zone_is_off_in_the_shipped_profiles() -> None:
    profiles = YamlProfileSource(CONFIG / "profiles")
    for name in profiles.names():
        assert {TREE_RULE, SHRUB_RULE} <= set(profiles.load(name).disabled_rules), name
