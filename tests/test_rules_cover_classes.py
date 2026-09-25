"""Каждый объект, на который сажать нельзя, виден размещению обоих видов посадки.

Индекс препятствий строится только по классам, у которых есть правило расстояния для этого
вида посадки: объект без правила для размещения невидим. Так куст вставал на опору, колодец
и ствол существующего дерева, а дерево - на ограду, памятник и существующий куст (25.09.2026).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString, Point

from green.application.constraints import ConstraintIndex
from green.domain.norms import PlantingType
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import CheckOutcome, Verdict
from green.infrastructure.config.repositories import YamlRuleBookSource

ROOT = Path(__file__).resolve().parents[1]
BOOK = YamlRuleBookSource(ROOT / "config" / "acts.yaml", ROOT / "config" / "rules.yaml").load()

# Не предметы на земле, а признаки и оформление; массив ограничивает посадку через покрытия.
NOT_OBSTACLES = frozenset(
    {
        ObjectClass.IGNORE,
        ObjectClass.UNKNOWN,
        ObjectClass.CONTOUR,
        ObjectClass.LAWN,
        ObjectClass.WORK_BOUNDARY,
        ObjectClass.EXISTING_WOODLAND,
    }
)
# СП 42.13330.2016, табл. 9.1: у кустарника прочерк - расстояние до подземной линейной сети
# не нормируется, кустарник над трубой допускается.
NO_SHRUB_NORM = frozenset(
    {
        ObjectClass.UTILITY_WATER,
        ObjectClass.UTILITY_SEWER,
        ObjectClass.UTILITY_STORM,
        ObjectClass.UTILITY_DRAIN,
        ObjectClass.UTILITY_GAS,
    }
)


@pytest.mark.parametrize("planting", [PlantingType.TREE, PlantingType.SHRUB])
def test_every_object_on_the_ground_has_a_distance_rule(planting: PlantingType) -> None:
    covered = {rule.object_class for rule in BOOK.distance_rules_for(planting)}
    exempt = NOT_OBSTACLES | (NO_SHRUB_NORM if planting is PlantingType.SHRUB else frozenset())

    assert sorted(c.value for c in ObjectClass if c not in covered | exempt) == []


@pytest.mark.parametrize("planting", [PlantingType.TREE, PlantingType.SHRUB])
def test_point_inside_a_closed_obstacle_is_rejected_by_the_obstacle_rule(
    planting: PlantingType,
) -> None:
    """Середина фонтана 20 x 20 м в 10 м от контура: по расстоянию до линии она проходила."""
    fountain = Feature(
        ref=SourceRef("00000000", "00000000", "1"),
        layer="Фонтаны",
        geometry=LineString([(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)]),
        object_class=ObjectClass.OBSTACLE,
    )
    rules = [r for r in BOOK.distance_rules_for(planting) if r.object_class is ObjectClass.OBSTACLE]
    index = ConstraintIndex([fountain], rules, require_utility_data=False)

    batch = index.evaluate(np.array([Point(10, 10), Point(10, 25)], dtype=object))

    assert [batch.verdict(0), batch.verdict(1)] == [Verdict.FORBIDDEN, Verdict.ALLOWED]
    failed = [c.rule_id for c in batch.checks(0) if c.outcome is CheckOutcome.FAIL]
    assert failed == [f"R-OBST-{planting.value.upper()}-001"]
