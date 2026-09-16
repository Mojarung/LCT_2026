"""Оценка пригодности: каждый фактор проверяется отдельно, веса нормируются."""

from __future__ import annotations

from dataclasses import replace

from green.application.assortment.context import SiteContext
from green.application.assortment.scoring import percent, score_species
from green.application.params import PlanParams
from green.domain.objects import ObjectClass
from green.domain.planting import LifeForm, Species

PARAMS = PlanParams()

BASE = Species(
    code="test_species",
    name_ru="Испытательный вид",
    name_lat="Testus testus",
    crown_diameter_m=3.0,
    genus="testus",
    family="Testaceae",
    life_form=LifeForm.TREE_MEDIUM,
    height_m=12.0,
    crown_mature_m=4.0,
    hardiness_zone=3,
    salt_tolerance=1,
    sources={"hardiness_zone": "справочник", "salt_tolerance": "справочник"},
)


def _ctx(
    *,
    kind: str | None = None,
    under_line: bool = False,
    **clearances: float,
) -> SiteContext:
    names = {"curb": ObjectClass.CURB, "road": ObjectClass.ROAD, "building": ObjectClass.BUILDING}
    return SiteContext(
        placement_id="p-1",
        x=0.0,
        y=0.0,
        clearance_m={names[key]: value for key, value in clearances.items()},
        under_overhead_line=under_line,
        structure_id="s-1" if kind else None,
        structure_kind=kind,
    )


def test_salt_tolerance_matters_next_to_the_carriageway_and_not_far_from_it() -> None:
    tolerant = replace(BASE, salt_tolerance=2, gas_tolerance=2)
    sensitive = replace(BASE, salt_tolerance=0, gas_tolerance=0)
    near = _ctx(curb=2.0)
    assert (
        score_species(tolerant, near, PARAMS).factors["site"]
        > (score_species(sensitive, near, PARAMS).factors["site"])
    )
    far = _ctx(curb=40.0)
    assert (
        score_species(tolerant, far, PARAMS).factors["site"]
        == score_species(sensitive, far, PARAMS).factors["site"]
    )


def test_weak_allergen_lowers_the_site_factor_anywhere() -> None:
    """Слабая аллергенность нормой не запрещена: штраф в оценке, одинаковый у жилья и вдали."""
    allergic = replace(BASE, allergen=1)
    neutral = replace(BASE, allergen=0)
    for ctx in (_ctx(building=15.0), _ctx(building=80.0)):
        assert (
            score_species(allergic, ctx, PARAMS).factors["site"]
            < score_species(neutral, ctx, PARAMS).factors["site"]
        )


def test_function_follows_the_structure_kind() -> None:
    row_species = replace(BASE, uses=frozenset({"row"}))
    group_species = replace(BASE, uses=frozenset({"group"}))
    row = _ctx(kind="row")
    assert score_species(row_species, row, PARAMS).factors["function"] == 1.0
    assert score_species(group_species, row, PARAMS).factors["function"] == 0.0
    group = _ctx(kind="group")
    assert score_species(group_species, group, PARAMS).factors["function"] == 1.0


def test_under_a_line_the_function_factor_asks_for_the_under_lines_use() -> None:
    low = replace(BASE, uses=frozenset({"row", "under_lines"}))
    tall = replace(BASE, uses=frozenset({"row"}))
    ctx = _ctx(kind="row", under_line=True)
    assert score_species(low, ctx, PARAMS).factors["function"] == 1.0
    assert score_species(tall, ctx, PARAMS).factors["function"] == 0.5


def test_decor_counts_peak_months_and_gives_evergreen_a_bonus() -> None:
    all_year = replace(BASE, decor_months=frozenset(range(1, 13)), evergreen=True)
    assert score_species(all_year, _ctx(), PARAMS).factors["decor"] == 1.0
    half = replace(BASE, decor_months=frozenset({1, 2, 3, 4, 5, 6}))
    assert score_species(half, _ctx(), PARAMS).factors["decor"] == 0.5
    conifer = replace(BASE, decor_months=frozenset({1, 2, 3}), evergreen=True)
    assert score_species(conifer, _ctx(), PARAMS).factors["decor"] == 0.5


def test_longevity_is_capped_and_care_is_stepped() -> None:
    assert (
        score_species(replace(BASE, lifespan_years=300), _ctx(), PARAMS).factors["longevity"] == 1.0
    )
    assert (
        score_species(replace(BASE, lifespan_years=75), _ctx(), PARAMS).factors["longevity"] == 0.5
    )
    assert score_species(replace(BASE, care_level=1), _ctx(), PARAMS).factors["care"] == 1.0
    assert score_species(replace(BASE, care_level=2), _ctx(), PARAMS).factors["care"] == 0.5
    assert score_species(replace(BASE, care_level=3), _ctx(), PARAMS).factors["care"] == 0.0


def test_pilot_factor_saturates_at_seven_streets() -> None:
    assert score_species(replace(BASE, pilot_streets=7), _ctx(), PARAMS).factors["pilot"] == 1.0
    assert score_species(replace(BASE, pilot_streets=14), _ctx(), PARAMS).factors["pilot"] == 1.0
    assert score_species(replace(BASE, pilot_streets=0), _ctx(), PARAMS).factors["pilot"] == 0.0


def test_weights_are_normalized_so_only_proportions_matter() -> None:
    species = replace(BASE, lifespan_years=150, care_level=1, pilot_streets=7)
    ctx = _ctx(kind="row")
    single = score_species(species, ctx, PARAMS).total
    doubled = replace(
        PARAMS,
        assortment_weights={name: 2 * w for name, w in PARAMS.assortment_weights.items()},
    )
    assert score_species(species, ctx, doubled).total == single


def test_a_single_weight_makes_the_score_that_factor() -> None:
    species = replace(BASE, lifespan_years=75)
    only_longevity = replace(PARAMS, assortment_weights={"longevity": 1.0})
    score = score_species(species, _ctx(), only_longevity)
    assert score.total == 0.5
    assert percent(score) == 50


def test_percent_rounds_the_total() -> None:
    species = replace(BASE, lifespan_years=100)
    score = score_species(species, _ctx(), replace(PARAMS, assortment_weights={"longevity": 1.0}))
    assert 0.66 < score.total < 0.67
    assert percent(score) == 67
