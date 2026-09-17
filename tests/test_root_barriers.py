"""Прикорневые барьеры: СП 42.13330.2016, табл. 9.1, прим. 5.

Дерево допускается ближе табличной нормы к сетям и бордюрам улиц: не ближе 0,5 м при высоте
кроны до 5 м и не ближе 1 м при высоте кроны 5-20 м. На здания, опоры и тротуары сокращение
не распространяется. Барьер становится условием посадки.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import shapely
from shapely.geometry import LineString, Polygon

from green.application.assortment.context import SiteContext
from green.application.assortment.filters import species_verdict
from green.application.barriers import barrier_distance
from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams, active_distance_rules
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import CheckOutcome, LifeForm, Species, Verdict
from green.infrastructure.config.repositories import YamlProfileSource, YamlRuleBookSource

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
PARAMS = PlanParams()
WITH_BARRIERS = replace(PARAMS, root_barriers=True)


def _feature(object_class: ObjectClass, geometry: shapely.Geometry, handle: str) -> Feature:
    return Feature(
        ref=SourceRef(file_sha8="0" * 8, xref_hash8="0" * 8, handle=handle),
        layer=object_class.value,
        geometry=geometry,
        object_class=object_class,
    )


CABLE = _feature(ObjectClass.UTILITY_POWER, LineString([(0, 0), (100, 0)]), "1")
HOUSE = _feature(ObjectClass.BUILDING, Polygon([(0, 20), (100, 20), (100, 30), (0, 30)]), "2")


def _index(barrier: float | None) -> ConstraintIndex:
    rules = active_distance_rules(RULEBOOK, PARAMS)
    return ConstraintIndex(
        [CABLE, HOUSE], rules, require_utility_data=True, barrier_distance_m=barrier
    )


def _tree(height_m: float) -> Species:
    return Species(
        code="test_tree",
        name_ru="Испытательное дерево",
        name_lat="Testus testus",
        crown_diameter_m=3.0,
        genus="testus",
        family="Testaceae",
        life_form=LifeForm.TREE_MEDIUM,
        height_m=height_m,
        crown_mature_m=4.0,
        hardiness_zone=3,
        salt_tolerance=2,
        sources={"hardiness_zone": "справочник", "salt_tolerance": "справочник"},
    )


def _near_cable(distance_m: float) -> SiteContext:
    return SiteContext(
        placement_id="p-1",
        x=0.0,
        y=0.0,
        clearance_m={ObjectClass.UTILITY_POWER: distance_m},
        under_overhead_line=False,
    )


def test_barrier_distance_follows_the_note() -> None:
    assert barrier_distance(4.0) == 0.5
    assert barrier_distance(5.0) == 1.0
    assert barrier_distance(20.0) == 1.0
    assert barrier_distance(25.0) is None


def test_point_closer_than_the_table_norm_passes_only_with_a_barrier() -> None:
    point = shapely.points([(50.0, 1.2)])
    assert _index(None).evaluate(point).verdict(0) is Verdict.FORBIDDEN
    batch = _index(0.5).evaluate(point)
    assert batch.verdict(0) is Verdict.ALLOWED
    assert batch.needs_barrier(0)
    cable = next(c for c in batch.checks(0) if c.rule_id == "R-POWER-TREE-001")
    assert cable.outcome is CheckOutcome.BARRIER


def test_barrier_does_not_help_closer_than_half_a_metre_or_near_a_building() -> None:
    index = _index(0.5)
    assert index.evaluate(shapely.points([(50.0, 0.3)])).verdict(0) is Verdict.FORBIDDEN
    near_house = index.evaluate(shapely.points([(50.0, 17.0)]))  # 3 м до стены при норме 5 м
    assert near_house.verdict(0) is Verdict.FORBIDDEN
    assert not near_house.needs_barrier(0)


def test_species_height_sets_the_required_distance() -> None:
    low, medium, tall = _tree(4.0), _tree(12.0), _tree(25.0)
    assert species_verdict(low, _near_cable(0.7), RULEBOOK, WITH_BARRIERS).allowed
    assert not species_verdict(medium, _near_cable(0.7), RULEBOOK, WITH_BARRIERS).allowed
    admitted = species_verdict(medium, _near_cable(1.2), RULEBOOK, WITH_BARRIERS)
    assert admitted.allowed
    (condition,) = [r for r in admitted.reasons if r.condition]
    assert condition.rule_id == "R-BARRIER-ROOT-001"
    assert "прим. 5" in condition.source
    assert "прикорневой барьер со стороны" in condition.condition
    assert not species_verdict(tall, _near_cable(1.5), RULEBOOK, WITH_BARRIERS).allowed


def test_without_the_profile_switch_the_table_norm_stays() -> None:
    assert not species_verdict(_tree(4.0), _near_cable(1.2), RULEBOOK, PARAMS).allowed


def test_barriers_profile_is_shipped() -> None:
    params = YamlProfileSource(CONFIG / "profiles").load("barriers")
    assert params.root_barriers
    assert min(params.curb_offsets_m) == 1.0
    assert params.curb_offsets_m[0] == 2.0  # сначала табличные отступы
