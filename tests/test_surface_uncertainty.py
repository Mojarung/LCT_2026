"""Missing or contradictory surface evidence must not become permission to plant."""

from __future__ import annotations

from pathlib import Path

import shapely
from shapely.geometry import LineString, Point, box

from green.application.params import PlanParams
from green.application.placement import GreedyPlantingStrategy
from green.application.surfaces import Material, build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel
from green.infrastructure.config.repositories import YamlRuleBookSource, YamlSpeciesCatalog

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULES = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
TREE = YamlSpeciesCatalog(CONFIG / "species.yaml").get("tilia_cordata")


def feature(cls: ObjectClass, geometry: shapely.Geometry, name: str = "object") -> Feature:
    return Feature(SourceRef("00000000", "00000000", name), name, geometry, object_class=cls)


def label(text: str, x: float, y: float) -> TextLabel:
    return TextLabel(SourceRef("00000000", "00000000", text), "labels", x, y, text)


def material(surface, x: float, y: float) -> Material:  # noqa: ANN001
    assert surface is not None
    return Material(surface.material(shapely.points([(x, y)]))[0])


def test_no_surface_evidence_means_no_automatic_planting() -> None:
    features = [
        feature(ObjectClass.WORK_BOUNDARY, box(0, 0, 100, 50)),
        feature(ObjectClass.CURB, LineString([(0, 10), (100, 10)])),
        feature(ObjectClass.UTILITY_WATER, LineString([(0, 45), (100, 45)])),
    ]
    plan = GreedyPlantingStrategy().plan(features, [], RULES, TREE, PlanParams())
    assert not plan.placements
    assert not plan.zones


def test_missing_work_boundary_does_not_mean_the_entire_drawing() -> None:
    features = [
        feature(ObjectClass.LAWN, box(0, 0, 100, 50)),
        feature(ObjectClass.CURB, LineString([(0, 10), (100, 10)])),
        feature(ObjectClass.UTILITY_WATER, LineString([(0, 45), (100, 45)])),
    ]
    labels = [label("А", 50, 5), label("ГАЗОН", 50, 20)]
    plan = GreedyPlantingStrategy().plan(features, labels, RULES, TREE, PlanParams())
    assert not plan.placements
    assert not plan.zones


def test_explicit_lawn_polygon_works_without_text_or_paved_seed() -> None:
    surface = build_surface_map(
        [feature(ObjectClass.LAWN, box(0, 0, 20, 20))],
        [],
        box(-5, -5, 25, 25),
        0.5,
    )
    assert material(surface, 10, 10) is Material.SOIL
    assert material(surface, -2, -2) is Material.UNKNOWN


def test_lawn_holes_are_not_soil() -> None:
    lawn = box(0, 0, 20, 20).difference(box(8, 8, 12, 12))
    surface = build_surface_map([feature(ObjectClass.LAWN, lawn)], [], box(-5, -5, 25, 25), 0.5)
    assert material(surface, 5, 5) is Material.SOIL
    assert material(surface, 10, 10) is Material.UNKNOWN


def test_exploratory_distance_mode_limits_label_reach() -> None:
    surface = build_surface_map(
        [],
        [label("ГАЗОН", 10, 10), label("А", 10, 90)],
        box(0, 0, 200, 100),
        0.5,
        inference_mode="distance",
    )
    assert material(surface, 150, 10) is Material.UNKNOWN
    assert material(surface, 12, 10) is Material.SOIL


def test_competing_labels_in_the_same_cell_remain_unknown_in_either_order() -> None:
    labels = [label("ГАЗОН", 10, 10), label("А", 10.1, 10.1)]
    for ordered in (labels, list(reversed(labels))):
        surface = build_surface_map([], ordered, box(0, 0, 20, 20), 0.5)
        assert material(surface, 10, 10) is Material.UNKNOWN
        assert material(surface, 15, 10) is Material.UNKNOWN


def test_tree_in_a_paved_square_is_not_evidence_of_a_large_lawn() -> None:
    surface = build_surface_map(
        [feature(ObjectClass.EXISTING_TREE, Point(10, 10))],
        [label("А", 90, 90)],
        box(0, 0, 100, 100),
        0.5,
    )
    assert material(surface, 20, 10) is Material.UNKNOWN


def test_explicit_pavement_overrides_an_inferred_soil_label() -> None:
    surface = build_surface_map(
        [feature(ObjectClass.SIDEWALK, box(0, 0, 20, 20))],
        [label("ГАЗОН", 10, 10), label("А", 25, 25)],
        box(-5, -5, 30, 30),
        0.5,
    )
    assert material(surface, 10, 10) is Material.PAVED
