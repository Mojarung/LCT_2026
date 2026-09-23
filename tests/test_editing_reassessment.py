"""Manual changes must update local suitability, conditions and explanations."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from shapely.geometry import LineString, box
from test_assortment_filters import CATALOG, RULEBOOK, _species
from test_surface_uncertainty import feature

from green.application.assortment.context import site_context
from green.application.assortment.scoring import percent, score_species
from green.application.barriers import BARRIER_CONDITION, BARRIER_NOTE
from green.application.editing import Edit, EditKind, RunContext, apply_edits, check_point
from green.application.errors import InputError
from green.application.params import PlanParams
from green.application.validation import validate_plan
from green.domain.norms import PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import (
    Alternative,
    AssortmentInfo,
    LifeForm,
    Placement,
    Plan,
    Reason,
    Species,
    Verdict,
)


def _plant(species: Species, *, identity: str = "p1", x: float = 10, y: float = 15) -> Placement:
    return Placement(identity, 1, PlantingType.TREE, species, x, y, Verdict.ALLOWED, ())


def _context(plants: tuple[Placement, ...], **params: object) -> RunContext:
    extent = box(-20, -20, 100, 80)
    features = (
        feature(ObjectClass.WORK_BOUNDARY, extent, "boundary"),
        feature(ObjectClass.LAWN, extent, "soil"),
        feature(ObjectClass.CURB, LineString([(-20, 0), (100, 0)]), "curb"),
    )
    settings = replace(PlanParams(require_utility_data=False, assortment_mode="single"), **params)
    return RunContext(
        "manual", features, (), settings, RULEBOOK, Plan(plants, ()), Path("unused"), 1
    )


def test_move_updates_fit_alternatives_and_structure_before_quality() -> None:
    chosen = _species(salt_tolerance=1, gas_tolerance=0, uses=frozenset({"row"}))
    sensitive = replace(chosen, code="sensitive", salt_tolerance=0)
    stale = AssortmentInfo(
        "assigned",
        99,
        {"site": 0.99},
        "old-row",
        "row",
        reasons=(Reason("composition", "old selection"),),
        alternatives=(Alternative(sensitive.code, sensitive.name_ru, 98, "old choice"),),
    )
    original = replace(_plant(chosen), assortment=stale)
    context = _context((original, _plant(chosen, identity="p2", x=16)))
    result = apply_edits(context, [Edit(EditKind.MOVE, "p1", 10, 3)], (chosen, sensitive))
    moved = result.placements[0]
    assert moved.species == chosen
    info = moved.assortment
    assert info is not None
    assert info.status == "manual"
    assert info.structure_kind == "single"
    expected = score_species(chosen, site_context(moved, structure_kind="single"), context.params)
    assert info.percent == percent(expected)
    assert info.factors == expected.factors
    assert sensitive.code not in {a.code for a in info.alternatives}
    assert not any(r.text == "old selection" for r in info.reasons)
    assert result.quality is not None
    fit = next(t for t in result.quality.terms if t.key == "fit")
    expected_fit = sum(p.assortment.percent for p in result.placements if p.assortment) / 200
    assert fit.score == pytest.approx(expected_fit)
    assert original.assortment == stale


@pytest.mark.parametrize("reason", ["salt", "hardiness", "invasive", "given"])
def test_point_check_enforces_species_constraints(reason: str) -> None:
    species = _species()
    params: dict[str, object] = {}
    if reason == "salt":
        species = replace(species, salt_tolerance=0)
    elif reason == "hardiness":
        species = replace(species, hardiness_zone=9)
    elif reason == "invasive":
        species = CATALOG.get("acer_negundo")
    else:
        params = {"assortment_mode": "given", "given_assortment": {"another": 1}}
    result = check_point(_context((), **params), 10, 3, species)
    assert result.verdict is Verdict.FORBIDDEN
    assert result.note


def test_move_into_salt_strip_explains_rejection_without_claiming_it_is_allowed() -> None:
    species = _species(salt_tolerance=0)
    result = apply_edits(
        _context((_plant(species),)), [Edit(EditKind.MOVE, "p1", 10, 3)], (species,)
    )
    assert not result.placements
    rejection = result.rejections[-1]
    assert rejection.verdict is Verdict.FORBIDDEN
    assert "реагенты" in rejection.note
    explanation = next(e.text for e in result.explanations if e.subject_id == "p1")
    assert "место допустимо" not in explanation


def test_move_away_removes_old_root_barrier_obligation() -> None:
    species = _species(height_m=12)
    original = replace(
        _plant(species, y=1.7),
        notes=(BARRIER_NOTE,),
        assortment=AssortmentInfo(
            "assigned", 90, {}, reasons=(Reason("norm", "old", condition=BARRIER_CONDITION),)
        ),
    )
    result = apply_edits(
        _context((original,), root_barriers=True), [Edit(EditKind.MOVE, "p1", 10, 15)], (species,)
    )
    moved = result.placements[0]
    assert BARRIER_NOTE not in moved.notes
    assert moved.assortment is not None
    assert not any(r.condition.startswith(BARRIER_CONDITION) for r in moved.assortment.reasons)


def test_added_conditional_shrub_has_documented_obligation() -> None:
    species = CATALOG.get("sorbaria_sorbifolia")
    context = _context(())
    result = apply_edits(
        context, [Edit(EditKind.ADD, x=10, y=15, species_code=species.code)], (species,)
    )
    info = result.placements[0].assortment
    assert info is not None
    assert any(r.condition and r.rule_id == "R-INVGROUP-THREE-001" for r in info.reasons)
    assert validate_plan(
        result, context.features, context.labels, RULEBOOK, context.params, catalog=(species,)
    ).ok


def test_deletion_rebuilds_neighbor_structure_and_keeps_species() -> None:
    species = _species(uses=frozenset({"row"}))
    plants = (_plant(species), _plant(species, identity="p2", x=16))
    result = apply_edits(_context(plants), [Edit(EditKind.DELETE, "p2")], (species,))
    assert result.placements[0].species == species
    assert result.placements[0].assortment is not None
    assert result.placements[0].assortment.structure_kind == "single"


def test_alternatives_use_their_own_species_distance_rules() -> None:
    chosen = _species(code="linden", name_lat="Tilia cordata", genus="tilia")
    birch = replace(chosen, code="birch", name_lat="Betula pendula", genus="betula")
    context = _context((_plant(chosen, y=20),))
    context.features = (
        *context.features,
        feature(ObjectClass.UTILITY_HEAT, LineString([(-20, 10), (100, 10)]), "heat"),
    )
    far = apply_edits(context, [], (chosen, birch)).placements[0]
    assert far.assortment is not None
    assert birch.code in {a.code for a in far.assortment.alternatives}
    near = apply_edits(context, [Edit(EditKind.MOVE, "p1", 10, 12.6)], (chosen, birch)).placements[
        0
    ]
    assert near.assortment is not None
    assert birch.code not in {a.code for a in near.assortment.alternatives}
    assert any(r.rule_id == "R-HEAT-TREE-002" for r in near.assortment.reasons)


@pytest.mark.parametrize(("x", "y"), [(float("nan"), 10), (10, float("inf")), (-float("inf"), 10)])
def test_nonfinite_manual_coordinates_are_rejected_before_geometry(x: float, y: float) -> None:
    species = _species()
    context = _context((_plant(species),))
    original = context.plan
    with pytest.raises(InputError, match="конечными"):
        apply_edits(context, [Edit(EditKind.MOVE, "p1", x, y)], (species,))
    assert context.plan is original


def test_conditional_warning_disappears_after_deleting_last_conditional_plant() -> None:
    species = CATALOG.get("sorbaria_sorbifolia")
    context = _context(())
    context.plan = apply_edits(
        context, [Edit(EditKind.ADD, x=10, y=15, species_code=species.code)], (species,)
    )
    assert any(w.startswith("Условие допуска:") for w in context.plan.warnings)
    result = apply_edits(
        context, [Edit(EditKind.DELETE, context.plan.placements[0].placement_id)], (species,)
    )
    assert not any(w.startswith("Условие допуска:") for w in result.warnings)


@pytest.mark.parametrize("failure", ["spacing", "given_count", "quota"])
def test_invalid_draft_has_no_quality_index_or_removal_advice(failure: str) -> None:
    species = _species()
    plants = (_plant(species), _plant(species, identity="p2", x=16))
    context = _context(plants)
    edits = [Edit(EditKind.MOVE, "p2", 11, 15)]
    if failure == "given_count":
        context.params = replace(
            context.params, assortment_mode="given", given_assortment={species.code: 1}
        )
        edits = []
    elif failure == "quota":
        context.params = replace(context.params, assortment_mode="auto")
        edits = []
    result = apply_edits(context, edits, (species,))
    assert len(result.placements) == 2, "The draft should remain editable"
    assert result.quality is not None
    assert result.quality.index is None
    assert not result.quality.values
    assert failure in result.quality.gate


def test_shrub_alternatives_exclude_other_life_forms() -> None:
    species = _species(life_form=LifeForm.SHRUB_LOW)
    groundcover = replace(species, code="groundcover", life_form=LifeForm.GROUNDCOVER)
    plant = replace(_plant(species), planting_type=PlantingType.SHRUB)
    result = apply_edits(_context((plant,)), [], (species, groundcover))
    assert result.placements[0].assortment is not None
    assert not result.placements[0].assortment.alternatives
