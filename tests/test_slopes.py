"""Откосы: СП 42.13330.2016, табл. 9.1, строка «Подошва откоса, террасы и др. | 1,0 | 0,5».

Слой «Откосы» есть в 89 чертежах датасета и раньше игнорировался. Расстояние считается до любого
элемента условного знака (бровка, штрихи), это строже нормы: на теле откоса посадок нет.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
import shapely
from shapely.geometry import LineString

from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams, active_distance_rules
from green.domain.norms import PlantingType
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import CheckOutcome, Verdict
from green.infrastructure.config.repositories import YamlLayerMapSource, YamlRuleBookSource

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
LAYER_MAP = YamlLayerMapSource(CONFIG / "layer_map.yaml").load()
TREES = PlanParams(require_utility_data=False)
SHRUBS = replace(TREES, planting_type=PlantingType.SHRUB)


def _feature(layer: str, object_class: ObjectClass = ObjectClass.UNKNOWN) -> Feature:
    return Feature(
        ref=SourceRef("00000000", "00000000", "1"),
        layer=layer,
        geometry=LineString([(0, 0), (100, 0)]),
        object_class=object_class,
    )


@pytest.mark.parametrize(
    "layer",
    [
        "Откосы",
        "Топо_Откосы",
        "output[1-12]_3_ДЖКХ-24_03233tp$0$Откосы",
        "Новый_Откосы_Ном._пера__99",
        "ДВ_ГП_Откос",
        "ДВ_ПП_П_Укрепление откосов",
    ],
)
def test_slope_layers_are_classified(layer: str) -> None:
    assert LAYER_MAP.classify(_feature(layer)) is ObjectClass.SLOPE


def test_contour_lines_stay_ignored() -> None:
    assert LAYER_MAP.classify(_feature("Горизонтали")) is ObjectClass.IGNORE


@pytest.mark.parametrize(
    ("params", "rule_id", "norm_m"),
    [(TREES, "R-SLOPE-TREE-001", 1.0), (SHRUBS, "R-SLOPE-SHRUB-001", 0.5)],
)
def test_planting_keeps_the_table_distance_from_a_slope(
    params: PlanParams, rule_id: str, norm_m: float
) -> None:
    slope = _feature("Откосы", ObjectClass.SLOPE)
    index = ConstraintIndex(
        [slope], active_distance_rules(RULEBOOK, params), require_utility_data=False
    )
    points = shapely.points([(50.0, norm_m - 0.1), (50.0, norm_m + 0.1)])
    batch = index.evaluate(points)
    assert batch.verdict(0) is Verdict.FORBIDDEN
    near, far = (
        next(c for c in batch.checks(position) if c.rule_id == rule_id) for position in (0, 1)
    )
    assert near.outcome is CheckOutcome.FAIL
    assert near.threshold_m == norm_m
    assert far.outcome is CheckOutcome.PASS


def test_slope_rules_quote_the_table_row() -> None:
    for rule_id in ("R-SLOPE-TREE-001", "R-SLOPE-SHRUB-001"):
        rule = RULEBOOK.rule(rule_id)
        assert rule is not None
        assert rule.citation.quote == "Подошва откоса, террасы и др. | 1,0 | 0,5"
        assert rule.citation.is_verified
