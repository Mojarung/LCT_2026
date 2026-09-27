"""Сеть - линия, даже если на её слое лежит замкнутая фигура (Харьковский проезд, 27.09.2026).

Слой «ЭН_ЗУ радиус 150м» нёс окружности радиусом 150 м; словарь вывел по «ЭН» силовой кабель,
окружность читалась площадью, и каждая точка внутри была «на кабеле»: 0 м, вся улица в отказах.
Расстояние до сети мерится до контура фигуры, и так же - в независимой проверке плана.
"""

from __future__ import annotations

from pathlib import Path

import shapely
from shapely.geometry import Point, box
from test_assortment_filters import CATALOG, RULEBOOK
from test_surface_uncertainty import feature

from green.application.constraints import ConstraintIndex, occupied_geometry
from green.application.params import PlanParams, active_distance_rules
from green.application.validation import validate_plan
from green.domain.norms import PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import Placement, Plan, Verdict
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]
CIRCLE = Point(0, 0).buffer(150, quad_segs=64)
LIME = next(s for s in CATALOG.all() if s.code == "tilia_cordata")


def _index(cls: ObjectClass) -> ConstraintIndex:
    rules = active_distance_rules(RULEBOOK, PlanParams())
    return ConstraintIndex([feature(cls, CIRCLE, "радиус")], rules, require_utility_data=True)


def test_a_closed_figure_on_a_cable_layer_is_measured_to_its_outline() -> None:
    batch = _index(ObjectClass.UTILITY_POWER).evaluate(shapely.points([(0, 0), (149.5, 0)]))

    assert batch.verdict(0) is Verdict.ALLOWED
    assert batch.verdict(1) is Verdict.FORBIDDEN


def test_a_manhole_still_occupies_its_area() -> None:
    manhole = feature(ObjectClass.UTILITY_ACCESS, Point(0, 0).buffer(0.8), "люк")
    assert occupied_geometry(manhole).geom_type == "Polygon"


def test_a_heat_chamber_drawn_as_an_area_keeps_its_area() -> None:
    """Камера 6 x 6 м на слое теплосети - сооружение: в её середине дерева нет."""
    chamber = feature(ObjectClass.UTILITY_HEAT, box(0, 0, 6, 6), "камера")
    assert occupied_geometry(chamber).geom_type == "Polygon"
    rules = active_distance_rules(RULEBOOK, PlanParams())
    index = ConstraintIndex([chamber], rules, require_utility_data=True)
    assert index.evaluate(shapely.points([(3, 3)])).verdict(0) is Verdict.FORBIDDEN


def test_plan_validation_measures_the_same_outline() -> None:
    placement = Placement("p", 1, PlantingType.TREE, LIME, 0.0, 0.0, Verdict.ALLOWED, ())
    features = (feature(ObjectClass.UTILITY_POWER, CIRCLE, "радиус"),)
    params = PlanParams(require_soil=False, require_work_boundary=False)
    report = validate_plan(
        Plan(placements=(placement,), rejections=()), features, (), RULEBOOK, params
    )

    assert not [i for i in report.issues if i.rule_id == "R-POWER-TREE-001"]


def test_a_radius_value_in_a_layer_name_is_drawing_annotation() -> None:
    vocabulary = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load().vocabulary
    inference = vocabulary.infer("НО_Харьковский проезд$0$ЭН_ЗУ радиус 150м")

    assert inference is not None
    assert inference.object_class is ObjectClass.IGNORE
