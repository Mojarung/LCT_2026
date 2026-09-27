"""Объяснение посадки ссылается на правила её вида, а не вида профиля (вычитка 27.09.2026).

Боярышник у дорожки получал трассу липы: без СП 82, п. 9.22 про колючие растения, зато с
«липа, клён у теплотрасс» у рябины. Проверка плана при этом мерила правильно.
"""

from __future__ import annotations

from shapely.geometry import LineString
from test_assortment_filters import CATALOG, RULEBOOK
from test_surface_uncertainty import feature

from green.application.params import PlanParams
from green.application.species_traces import with_species_traces
from green.domain.norms import PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import Placement, Plan, Verdict

SPECIES = {s.code: s for s in CATALOG.all()}


def _plant(code: str, identity: str, x: float, y: float) -> Placement:
    return Placement(identity, 1, PlantingType.TREE, SPECIES[code], x, y, Verdict.ALLOWED, ())


def _traced(*plants: Placement) -> dict[str, set[str]]:
    features = (
        feature(ObjectClass.PAVEMENT_EDGE, LineString([(0, 0), (100, 0)]), "дорожка"),
        feature(ObjectClass.UTILITY_HEAT, LineString([(0, 30), (100, 30)]), "теплосеть"),
        feature(ObjectClass.UTILITY_POWER, LineString([(0, 60), (100, 60)]), "кабель"),
    )
    plan = Plan(placements=plants, rejections=())
    traced = with_species_traces(plan, features, RULEBOOK, PlanParams())
    return {p.placement_id: {c.rule_id for c in p.checks} for p in traced.placements}


def test_a_thorny_tree_is_traced_by_the_thorny_rule() -> None:
    rules = _traced(_plant("crataegus_laevigata", "hawthorn", 10, 3))

    assert "R-THORNPV-TREE-001" in rules["hawthorn"]


def test_a_genus_rule_of_the_profile_species_does_not_leak_to_another_genus() -> None:
    rules = _traced(
        _plant("sorbus_aucuparia", "rowan", 10, 33), _plant("tilia_cordata", "lime", 40, 33)
    )

    assert "R-HEAT-TREE-002" not in rules["rowan"]
    assert "R-HEAT-TREE-002" in rules["lime"]


def test_the_verdict_is_kept_and_every_placement_keeps_its_place() -> None:
    plants = (_plant("sorbus_aucuparia", "a", 10, 45), _plant("crataegus_laevigata", "b", 50, 45))
    features = (feature(ObjectClass.UTILITY_POWER, LineString([(0, 60), (100, 60)]), "кабель"),)
    traced = with_species_traces(
        Plan(placements=plants, rejections=()), features, RULEBOOK, PlanParams()
    )

    assert [(p.placement_id, p.x, p.y, p.verdict) for p in traced.placements] == [
        (p.placement_id, p.x, p.y, p.verdict) for p in plants
    ]
