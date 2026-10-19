"""Target carriageway before 'за Тротуар' must retain its road clearance."""

from __future__ import annotations

from pathlib import Path

import pytest
import shapely
from shapely.geometry import box

from green.application.classification import classify_scene
from green.application.constraints import ConstraintIndex
from green.application.params import PlanParams
from green.domain.objects import Feature, ObjectClass, Scene, SourceRef
from green.domain.planting import Verdict
from green.infrastructure.config.repositories import YamlLayerMapSource, YamlRuleBookSource

ROOT = Path(__file__).resolve().parents[1]
MAPPING = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
ROAD = "ДВ_ПП_Тип4_ПЧ местные за Тротуар АБ"


def classified(layer: str) -> Scene:
    feature = Feature(
        SourceRef("00000000", "00000000", "1"),
        layer,
        box(0, 0, 10, 10),
        source_entity_type="HATCH",
    )
    scene = Scene("transition.dxf", "0" * 64, "AC1032", (feature,))
    return classify_scene(scene, MAPPING, PlanParams(name_model=False))[0]


@pytest.mark.parametrize(
    ("layer", "expected"),
    [
        (ROAD, ObjectClass.ROAD),
        (f"xref|{ROAD}", ObjectClass.ROAD),
        (f"xref$0${ROAD}", ObjectClass.ROAD),
        (ROAD.lower(), ObjectClass.ROAD),
        ("ДВ_ПП_Тип4_Газон за ПЧ", ObjectClass.LAWN),
        ("ДВ_ПП_Тип4_Тротуар за ПЧ", ObjectClass.SIDEWALK),
    ],
)
def test_explicit_target_wins_over_replaced_surface(layer: str, expected: ObjectClass) -> None:
    assert classified(layer).features[0].object_class is expected


def test_target_road_keeps_two_metre_tree_clearance() -> None:
    rulebook = YamlRuleBookSource(ROOT / "config/acts.yaml", ROOT / "config/rules.yaml").load()
    rules = tuple(
        rule
        for rule in rulebook.for_sp42_edition("2016").distance_rules
        if rule.rule_id in {"R-ROAD-TREE-001", "R-SWALK-TREE-001"}
    )
    index = ConstraintIndex(
        classified(ROAD).features,
        rules,
        require_utility_data=False,
        planting_radius_m=1.24,
    )
    points = shapely.points([(11.5, 5), (5, 5)])
    batch = index.evaluate(points)
    assert batch.verdict(0) is Verdict.FORBIDDEN
    assert index.plantable(points).tolist() == [True, False]
    assert any(
        check.rule_id == "R-ROAD-TREE-001" and check.threshold_m == 2 and check.measured_m == 1.5
        for check in batch.checks(0)
    )
