"""Current counts/quotas must describe edited plants, including both life forms."""

from __future__ import annotations

from dataclasses import replace

import pytest

from green.application.assortment.assign import Assignment
from green.application.assortment.summary import build_summary, refresh_summaries
from green.application.params import PlanParams
from green.domain.norms import PlantingType
from green.domain.planting import AssortmentSummary, LifeForm, Placement, Plan, Species, Verdict

TREE = Species("t", "tree", "tree", 3, genus="tg", family="tf", decor_months=frozenset({5}))
SHRUB = Species(
    "s",
    "shrub",
    "shrub",
    1,
    genus="sg",
    family="sf",
    life_form=LifeForm.SHRUB_LOW,
    decor_months=frozenset({5, 9}),
)
OTHER = replace(TREE, code="u", genus="ug", family="uf", decor_months=frozenset({9}))
CATALOG = (TREE, SHRUB, OTHER)


def _placement(number: int, species: Species) -> Placement:
    return Placement(
        str(number),
        number,
        PlantingType.TREE if species.is_tree else PlantingType.SHRUB,
        species,
        number * 6,
        5,
        Verdict.ALLOWED,
        (),
    )


def _old_summary(species: Species, count: int = 10) -> AssortmentSummary:
    return build_summary(
        Assignment({str(i): species.code for i in range(count)}, solver="milp"),
        {s.code: s for s in CATALOG},
        {species.code: 2},
        mode="auto",
        no_species=3,
        rejected_by_kind={"norm": 12},
        rejected_by_rule={"R-X": 12},
    )


def test_mixed_counts_and_seasons_are_current_and_diagnostics_are_history() -> None:
    plan = Plan(
        (_placement(1, TREE), _placement(2, OTHER), _placement(3, SHRUB)),
        (),
        assortment_summary=_old_summary(TREE),
        shrub_assortment_summary=_old_summary(SHRUB),
    )
    result = refresh_summaries(plan, PlanParams(), CATALOG)
    trees, shrubs = result.assortment_summary, result.shrub_assortment_summary
    assert trees is not None
    assert shrubs is not None
    assert trees.counts == {"t": 1, "u": 1}
    assert shrubs.counts == {"s": 1}
    assert trees.genus_shares == {"tg": 0.5, "ug": 0.5}
    assert trees.family_shares == {"tf": 0.5, "uf": 0.5}
    assert trees.decor_by_month[5] == trees.decor_by_month[9] == 1
    assert shrubs.decor_by_month[5] == shrubs.decor_by_month[9] == 1
    assert trees.solver == shrubs.solver == "manual"
    assert trees.existing == {"t": 2}
    assert trees.no_species == 3
    assert trees.rejected_by_rule == {"R-X": 12}
    assert "исходный подбор" in trees.notes[0]
    assert result.placements == plan.placements
    assert plan.assortment_summary is not None
    assert plan.assortment_summary.counts == {"t": 10}


def test_emptying_both_populations_clears_shares_and_months() -> None:
    plan = Plan(
        (), (), assortment_summary=_old_summary(TREE), shrub_assortment_summary=_old_summary(SHRUB)
    )
    result = refresh_summaries(plan, PlanParams(), CATALOG)
    for summary in (result.assortment_summary, result.shrub_assortment_summary):
        assert summary is not None
        assert summary.counts == summary.genus_shares == summary.family_shares == {}
        assert summary.conifer_share == summary.shannon == 0
        assert not any(summary.decor_by_month.values())
        assert not summary.quota_violations


@pytest.mark.parametrize("kind", [PlantingType.SHRUB, PlantingType.HEDGE])
def test_standalone_shrubs_use_primary_summary_and_quotas(kind: PlantingType) -> None:
    plants = tuple(_placement(i, SHRUB) for i in range(1, 4))
    plan = Plan(plants, ())
    result = refresh_summaries(plan, PlanParams(planting_type=kind, quota_species=0.1), CATALOG)
    assert result.assortment_summary is not None
    assert result.assortment_summary.counts == {"s": 3}
    assert result.shrub_assortment_summary is None
    assert (
        "Превышена квота разнообразия: вид s - 3 при пределе 1"
        in result.assortment_summary.quota_violations
    )


def test_added_shrubs_get_a_summary_even_if_original_plan_had_none() -> None:
    result = refresh_summaries(Plan((_placement(1, SHRUB),), ()), PlanParams(), CATALOG)
    assert result.assortment_summary is not None
    assert result.shrub_assortment_summary is not None
    assert result.assortment_summary.counts == {}
    assert result.shrub_assortment_summary.counts == {"s": 1}


@pytest.mark.parametrize("mode", ["single", "given"])
def test_current_manual_counts_respect_composition_mode(mode: str) -> None:
    plan = Plan(tuple(_placement(i, TREE) for i in range(1, 4)), ())
    params = PlanParams(assortment_mode=mode, given_assortment={"t": 2})
    result = refresh_summaries(plan, params, CATALOG)
    assert result.assortment_summary is not None
    assert result.assortment_summary.mode == mode
    assert result.assortment_summary.counts == {"t": 3}
    assert bool(result.assortment_summary.quota_violations) is (mode == "given")


def test_inventory_can_block_new_plants_even_with_small_current_counts() -> None:
    plan = Plan((_placement(1, TREE),), (), assortment_summary=_old_summary(TREE))
    result = refresh_summaries(plan, PlanParams(), CATALOG)
    assert result.assortment_summary is not None
    assert result.assortment_summary.existing == {"t": 2}
    assert (
        "Превышена квота разнообразия: вид t - 1 при пределе 0"
        in result.assortment_summary.quota_violations
    )
