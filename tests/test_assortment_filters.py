"""Жёсткие фильтры: по одному случаю на каждое основание отказа из спецификации."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from green.application.assortment.context import SiteContext
from green.application.assortment.filters import NORM, PARAMETER, REFERENCE, species_verdict
from green.application.params import PlanParams
from green.domain.objects import ObjectClass
from green.domain.planting import LifeForm, Species
from green.infrastructure.config.repositories import YamlRuleBookSource, YamlSpeciesCatalog

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
CATALOG = YamlSpeciesCatalog(CONFIG / "species.yaml")
PARAMS = PlanParams()


def _species(**overrides: object) -> Species:
    base = Species(
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
    return replace(base, **overrides)  # type: ignore[arg-type]


def _fix(clearances: dict[str, float]) -> list[tuple[str, float]]:
    names = {
        "heat": "utility.heat",
        "building": "building",
        "curb": "curb",
        "road": "road",
        "power": "utility.power_cable",
        "sidewalk": "sidewalk",
        "pavement": "pavement_edge",
    }
    return [(names[key], value) for key, value in clearances.items()]


def _ctx_of(*, under_line: bool = False, **clearances: float) -> SiteContext:
    return SiteContext(
        placement_id="p-1",
        x=0.0,
        y=0.0,
        clearance_m={ObjectClass(name): value for name, value in _fix(clearances)},
        under_overhead_line=under_line,
    )


def test_group_two_invasive_is_rejected_on_any_territory() -> None:
    for territory in ("green_fund", "protected_green", "natural", "outside_green_fund"):
        params = replace(PARAMS, territory=territory)
        verdict = species_verdict(CATALOG.get("acer_negundo"), _ctx_of(), RULEBOOK, params)
        assert not verdict.allowed
        blocking = verdict.blocking
        assert blocking is not None
        assert blocking.kind == NORM
        assert blocking.rule_id == "R-INV-ACERNEG-001"
        assert "группы II" in blocking.text
        assert "п. 2.1" in blocking.source
        assert "п. 4.1" in blocking.source


def test_group_three_is_conditional_on_green_fund_and_forbidden_on_protected_land() -> None:
    """369-ПП прил. 2: п. 5.3 допускает высадку на иных территориях зелёного фонда с мерами
    против распространения, п. 5.2 запрещает на особо охраняемых зелёных и природных."""
    sorbaria = CATALOG.get("sorbaria_sorbifolia")
    admitted = species_verdict(sorbaria, _ctx_of(), RULEBOOK, PARAMS)
    assert admitted.allowed
    conditional = [r for r in admitted.reasons if r.condition]
    assert len(conditional) == 1
    assert conditional[0].rule_id == "R-INVGROUP-THREE-001"
    assert "распространения" in conditional[0].condition
    for territory in ("protected_green", "natural", "outside_green_fund"):
        params = replace(PARAMS, territory=territory)
        rejected = species_verdict(sorbaria, _ctx_of(), RULEBOOK, params)
        assert not rejected.allowed, territory
        assert rejected.blocking is not None
        assert rejected.blocking.rule_id == "R-INV-SORBAR-001"


def test_genus_wide_listing_catches_any_species_of_the_genus() -> None:
    """«Reynoutria ssp.» в перечне: запрещён любой вид рода."""
    knotweed = _species(name_lat="Reynoutria japonica", genus="reynoutria")
    verdict = species_verdict(knotweed, _ctx_of(), RULEBOOK, PARAMS)
    assert not verdict.allowed
    assert verdict.blocking is not None
    assert verdict.blocking.rule_id == "R-INV-REYNOU-001"


def test_genus_rule_rejects_birch_and_admits_linden_at_the_same_distance() -> None:
    ctx = _ctx_of(heat=2.6)
    birch = _species(name_lat="Betula pendula", genus="betula")
    linden = _species(name_lat="Tilia cordata", genus="tilia")
    rejected = species_verdict(birch, ctx, RULEBOOK, PARAMS)
    assert not rejected.allowed
    assert rejected.blocking is not None
    assert rejected.blocking.rule_id == "R-HEAT-TREE-003"
    assert "берёз" in rejected.blocking.source or "берез" in rejected.blocking.source
    admitted = species_verdict(linden, ctx, RULEBOOK, PARAMS)
    assert admitted.allowed
    assert any(r.rule_id == "R-HEAT-TREE-002" for r in admitted.reasons)


def test_crown_wider_than_five_metres_raises_the_table_thresholds() -> None:
    wide = _species(crown_mature_m=12.0)
    narrow = _species(crown_mature_m=4.0)
    ctx = _ctx_of(building=6.0)
    rejected = species_verdict(wide, ctx, RULEBOOK, PARAMS)
    assert not rejected.allowed
    assert rejected.blocking is not None
    assert rejected.blocking.rule_id == "R-BLD-TREE-001"
    assert "8.5" in rejected.blocking.text.replace(",", ".")
    assert "толкование проекта" in rejected.blocking.text
    assert species_verdict(narrow, ctx, RULEBOOK, PARAMS).allowed


def test_crown_increase_is_switched_off_by_the_project_parameter() -> None:
    wide = _species(crown_mature_m=12.0)
    params = replace(PARAMS, crown_extra_per_m=0.0)
    assert species_verdict(wide, _ctx_of(curb=2.0), RULEBOOK, params).allowed


def test_wide_crown_keeps_ten_metres_from_buildings_by_743_pp() -> None:
    """743-ПП, прим. 3 к табл. 3.6.1: широкая крона не ближе 10 м от здания, без коэффициентов."""
    wide = _species(crown_mature_m=12.0)
    params = replace(PARAMS, crown_extra_per_m=0.0)
    rejected = species_verdict(wide, _ctx_of(building=9.0), RULEBOOK, params)
    assert not rejected.allowed
    assert rejected.blocking is not None
    assert rejected.blocking.rule_id == "R-BLDCROWN-TREE-001"
    assert "прим. 3" in rejected.blocking.source
    assert species_verdict(wide, _ctx_of(building=10.5), RULEBOOK, params).allowed
    narrow = _species(crown_mature_m=5.0)
    assert species_verdict(narrow, _ctx_of(building=5.5), RULEBOOK, params).allowed


def test_only_low_species_stay_under_an_overhead_line() -> None:
    ctx = _ctx_of(under_line=True)
    tall = species_verdict(_species(height_m=25.0), ctx, RULEBOOK, PARAMS)
    assert not tall.allowed
    assert tall.blocking is not None
    assert tall.blocking.kind == NORM
    assert tall.blocking.rule_id == "R-OHL-TREE-001"
    assert species_verdict(_species(height_m=3.5), ctx, RULEBOOK, PARAMS).allowed


def test_female_fluff_is_rejected_anywhere_in_the_city() -> None:
    """743-ПП п. 3.6.18 запрещает посадку «в городе»: расстояние до жилья не при чём."""
    fluffy = _species(fluff=True, sources={"hardiness_zone": "a", "salt_tolerance": "b"})
    for ctx in (_ctx_of(building=12.0), _ctx_of(building=500.0), _ctx_of()):
        verdict = species_verdict(fluffy, ctx, RULEBOOK, PARAMS)
        assert not verdict.allowed
        assert verdict.blocking is not None
        assert verdict.blocking.kind == NORM
        assert verdict.blocking.rule_id == "R-PPSEVEN-FLUFF-001"
        assert "3.6.18" in verdict.blocking.source


def test_male_clone_passes_with_a_condition_on_planting_material() -> None:
    poplar = CATALOG.get("populus_simonii")
    verdict = species_verdict(poplar, _ctx_of(), RULEBOOK, PARAMS)
    assert verdict.allowed
    assert any("мужские" in r.condition for r in verdict.reasons)
    assert not species_verdict(
        CATALOG.get("populus_balsamifera"), _ctx_of(), RULEBOOK, PARAMS
    ).allowed


def test_mass_allergen_without_an_act_recommendation_is_rejected_by_743_pp() -> None:
    """Лещина: массовый аллерген по справочнику, в табл. В.6 МГСН её нет - запрет п. 3.6.18."""
    verdict = species_verdict(CATALOG.get("corylus_avellana"), _ctx_of(), RULEBOOK, PARAMS)
    assert not verdict.allowed
    assert verdict.blocking is not None
    assert verdict.blocking.rule_id == "R-PPSEVEN-ALLERGEN-001"
    assert "отнесение вида" in verdict.blocking.text


def test_birch_recommended_by_the_moscow_act_is_not_banned_as_an_allergen() -> None:
    """МГСН 1.02-02 табл. В.6 и 515-ПП рекомендуют берёзу: справочная аллергенность не запрет."""
    birch = CATALOG.get("betula_pendula")
    for category in ("streets", "yards", "parks"):
        verdict = species_verdict(
            birch, _ctx_of(), RULEBOOK, replace(PARAMS, planting_category=category)
        )
        assert verdict.allowed, category
        assert any("п. 3.6.18 743-ПП не применён" in r.text for r in verdict.reasons)


def test_species_marked_minus_for_the_category_is_rejected() -> None:
    """Лох узколистный: «-» для улиц и дорог, «+» для внутриквартальных посадок."""
    olive = CATALOG.get("elaeagnus_angustifolia")
    on_street = species_verdict(olive, _ctx_of(), RULEBOOK, PARAMS)
    assert not on_street.allowed
    assert on_street.blocking is not None
    assert on_street.blocking.rule_id == "R-MGSN-CATEGORY-001"
    assert "улицы и дороги" in on_street.blocking.text
    assert "В.6" in on_street.blocking.source
    in_yard = species_verdict(
        olive, _ctx_of(), RULEBOOK, replace(PARAMS, planting_category="yards")
    )
    assert in_yard.allowed


def test_limited_mark_is_said_in_the_reasons() -> None:
    linden = CATALOG.get("tilia_cordata")
    verdict = species_verdict(linden, _ctx_of(), RULEBOOK, PARAMS)
    assert verdict.allowed
    assert any(
        "с ограничением" in r.text and r.rule_id == "R-MGSN-CATEGORY-001" for r in verdict.reasons
    )


def test_fruit_litter_is_rejected_by_743_pp() -> None:
    litter = _species(fruit_litter=True, sources={"hardiness_zone": "a", "salt_tolerance": "b"})
    verdict = species_verdict(litter, _ctx_of(), RULEBOOK, PARAMS)
    assert not verdict.allowed
    assert verdict.blocking is not None
    assert verdict.blocking.rule_id == "R-PPSEVEN-LITTER-001"


def test_species_from_a_warmer_zone_is_rejected_as_a_reference_reason() -> None:
    tender = _species(hardiness_zone=6)
    verdict = species_verdict(tender, _ctx_of(), RULEBOOK, PARAMS)
    assert not verdict.allowed
    assert verdict.blocking is not None
    assert verdict.blocking.kind == REFERENCE
    assert verdict.blocking.rule_id == ""


def test_salt_intolerant_species_is_rejected_next_to_the_carriageway() -> None:
    tender = _species(salt_tolerance=0)
    near = species_verdict(tender, _ctx_of(curb=2.4), RULEBOOK, PARAMS)
    assert not near.allowed
    assert near.blocking is not None
    assert near.blocking.kind == REFERENCE
    assert species_verdict(tender, _ctx_of(curb=9.0), RULEBOOK, PARAMS).allowed


def test_given_mode_rejects_everything_outside_the_list() -> None:
    params = replace(PARAMS, assortment_mode="given", given_assortment={"tilia_cordata": 10})
    outside = species_verdict(_species(), _ctx_of(), RULEBOOK, params)
    assert not outside.allowed
    assert outside.blocking is not None
    assert outside.blocking.kind == PARAMETER
    inside = species_verdict(_species(code="tilia_cordata"), _ctx_of(), RULEBOOK, params)
    assert inside.allowed


def test_admitted_species_carries_positive_reasons_with_numbers() -> None:
    salt_proof = _species(
        name_lat="Tilia cordata", genus="tilia", salt_tolerance=2, pilot_streets=4
    )
    verdict = species_verdict(salt_proof, _ctx_of(curb=2.4, heat=3.0), RULEBOOK, PARAMS)
    assert verdict.allowed
    kinds = {r.kind for r in verdict.reasons}
    assert NORM in kinds
    assert REFERENCE in kinds
    assert any("2.4" in r.text.replace(",", ".") for r in verdict.reasons)


def test_crown_increase_applies_to_every_row_of_the_table_by_default() -> None:
    """Прим. 1 к табл. 9.1 написано для всей таблицы: по умолчанию увеличение везде.

    Липа с кроной 12 м: борт 2 + 3,5 = 5,5 м, силовой кабель 2 + 3,5 = 5,5 м.
    """
    linden = CATALOG.get("tilia_cordata")
    assert not species_verdict(linden, _ctx_of(curb=2.0), RULEBOOK, PARAMS).allowed
    assert not species_verdict(linden, _ctx_of(power=2.6), RULEBOOK, PARAMS).allowed
    assert species_verdict(linden, _ctx_of(curb=5.6, power=5.6), RULEBOOK, PARAMS).allowed


def test_narrowed_crown_classes_are_an_explicit_profile_deviation() -> None:
    linden = CATALOG.get("tilia_cordata")
    narrowed = replace(PARAMS, crown_extra_classes=("building", "structure"))
    assert species_verdict(linden, _ctx_of(curb=2.0), RULEBOOK, narrowed).allowed


@pytest.mark.parametrize("code", ["cotinus_coggygria", "forsythia_ovata", "weigela_florida"])
def test_zone_five_species_need_an_explicit_regional_profile(code: str) -> None:
    """Скумпия, форзиция и вейгела есть в паспортах пилота, но по зоне в Москве подмерзают."""
    species = CATALOG.get(code)
    assert not species_verdict(species, _ctx_of(), RULEBOOK, PARAMS).allowed
    warmer = replace(PARAMS, region_hardiness_zone=5)
    assert species_verdict(species, _ctx_of(), RULEBOOK, warmer).allowed


def test_thorny_plants_keep_two_metres_from_pedestrian_ways() -> None:
    """СП 82.13330.2016 п. 9.22: колючие растения не ближе 2 м от пешеходных коммуникаций."""
    hawthorn = CATALOG.get("crataegus_laevigata")
    assert "thorny" in hawthorn.traits
    for where in ("sidewalk", "pavement"):
        near = species_verdict(hawthorn, _ctx_of(**{where: 1.4}), RULEBOOK, PARAMS)
        assert not near.allowed, where
        assert near.blocking is not None
        assert near.blocking.rule_id.startswith("R-THORN"), near.blocking.rule_id
        assert "9.22" in near.blocking.source
        assert "колючее" in near.blocking.text
        assert species_verdict(hawthorn, _ctx_of(**{where: 2.5}), RULEBOOK, PARAMS).allowed
    smooth = _species(crown_mature_m=4.0)
    assert species_verdict(smooth, _ctx_of(sidewalk=1.4), RULEBOOK, PARAMS).allowed
