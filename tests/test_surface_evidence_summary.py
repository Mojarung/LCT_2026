"""Do not present inferred planting pits as confirmed material geometry."""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import shapely
from shapely.geometry import box

from green.application.params import PlanParams
from green.application.results import IntegrityReport, RunReport
from green.application.surfaces import Material, SurfaceMap
from green.domain.norms import PlantingType, RuleBook
from green.domain.planting import LifeForm, Placement, Plan, Species, Verdict
from green.infrastructure.config.repositories import YamlProfileSource

TREE = Species("tree", "tree", "tree", 4)
SHRUB = Species("shrub", "shrub", "shrub", 1, life_form=LifeForm.SHRUB_LOW)


def surface() -> SurfaceMap:
    return SurfaceMap(
        np.full((12, 12), Material.SOIL, dtype=np.int8), (0, 0), 1, 0, 1, soil_area=box(2, 2, 8, 8)
    )


def report(species: Species, x: float, material: SurfaceMap | None) -> RunReport:
    plant = Placement(
        "p1",
        1,
        PlantingType.TREE if species.is_tree else PlantingType.SHRUB,
        species,
        x,
        5,
        Verdict.ALLOWED,
        (),
    )
    return RunReport(
        "test",
        "source.dxf",
        "hash",
        "AC1032",
        "strict",
        PlanParams(),
        RuleBook({}, (), "test"),
        "layers",
        (),
        {},
        Plan((plant,), ()),
        IntegrityReport(0, 0, (), (), ()),
        (),
        Path("result.dxf"),
        None,
        surface=material,
    )


def test_an_inside_centre_is_not_enough_to_confirm_the_whole_pit() -> None:
    points = shapely.points([(2.25, 5), (3.25, 5), (9, 5)])
    material = surface()
    assert material.fits_soil(points, 0.5).tolist() == [True, True, True]
    assert material.fits_confirmed_soil(points, 0.5).tolist() == [False, True, False]


@pytest.mark.parametrize("obstacle", ["paved_area", "uncertainty_area", "woodland_area"])
def test_exact_ground_does_not_confirm_a_pit_crossing_an_exclusion(obstacle: str) -> None:
    material = replace(surface(), **{obstacle: box(5.4, 4, 6, 6)})
    assert not material.fits_confirmed_soil(shapely.points([(5, 5)]), 0.5)[0]


def test_summary_uses_the_radius_of_the_placed_species() -> None:
    # 0.75 m from the confirmed edge: a shrub pit fits, a tree pit crosses it.
    shrub = report(SHRUB, 2.75, surface()).summary()
    tree = report(TREE, 2.75, surface()).summary()
    assert shrub["surface_confirmed_placements"] == 1
    assert shrub["surface_unconfirmed_placements"] == 0
    assert shrub["surface_inference_review_required"] is False
    assert tree["surface_confirmed_placements"] == 0
    assert tree["surface_unconfirmed_placements"] == 1
    assert tree["surface_inference_review_required"] is True


def test_missing_map_and_manual_moves_do_not_keep_a_stale_confirmation() -> None:
    initial = report(SHRUB, 5, surface())
    assert initial.summary()["surface_confirmed_placements"] == 1
    moved = replace(
        initial, plan=replace(initial.plan, placements=(replace(initial.plan.placements[0], x=9),))
    )
    assert moved.summary()["surface_unconfirmed_placements"] == 1
    assert replace(initial, surface=None).summary()["surface_inference_review_required"] is True
    empty = replace(initial, plan=Plan((), ()))
    assert empty.summary()["surface_unconfirmed_placements"] == 0
    assert empty.summary()["surface_inference_review_required"] is False


def test_review_profile_changes_only_semantic_inference() -> None:
    profiles = YamlProfileSource(Path(__file__).resolve().parents[1] / "config/profiles")
    assert profiles.load("review") == replace(profiles.load("strict"), infer_unknown=False)
