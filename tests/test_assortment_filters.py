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


def test_invasive_species_is_rejected_by_the_ban_rule() -> None:
    verdict = species_verdict(CATALOG.get("acer_negundo"), _ctx_of(), RULEBOOK, PARAMS)
    assert not verdict.allowed
    blocking = verdict.blocking
    assert blocking is not None
    assert blocking.kind == NORM
    assert blocking.rule_id == "R-INV-ACERNEG-001"
    assert "369-ПП" in blocking.source


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
    assert species_verdict(narrow, ctx, RULEBOOK, PARAMS).allowed


def test_crown_increase_is_switched_off_by_the_project_parameter() -> None:
    wide = _species(crown_mature_m=12.0)
    params = replace(PARAMS, crown_extra_per_m=0.0)
    assert species_verdict(wide, _ctx_of(building=6.0), RULEBOOK, params).allowed


def test_only_low_species_stay_under_an_overhead_line() -> None:
    ctx = _ctx_of(under_line=True)
    tall = species_verdict(_species(height_m=25.0), ctx, RULEBOOK, PARAMS)
    assert not tall.allowed
    assert tall.blocking is not None
    assert tall.blocking.kind == NORM
    assert tall.blocking.rule_id == "R-OHL-TREE-001"
    assert species_verdict(_species(height_m=3.5), ctx, RULEBOOK, PARAMS).allowed


def test_fluffy_species_is_rejected_near_housing_and_admitted_away_from_it() -> None:
    fluffy = _species(fluff=True)
    near = species_verdict(fluffy, _ctx_of(building=12.0), RULEBOOK, PARAMS)
    assert not near.allowed
    assert near.blocking is not None
    assert near.blocking.kind == NORM
    assert "743-ПП" in near.blocking.source
    assert "3.6.18" in near.blocking.source
    assert species_verdict(fluffy, _ctx_of(building=60.0), RULEBOOK, PARAMS).allowed


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


def test_real_linden_needs_more_room_from_a_heat_network_than_the_table_says() -> None:
    """Следствие прим. к табл. 9.1 на реальных данных: крона 12 м поднимает 2,0 м до 5,5 м."""
    linden = CATALOG.get("tilia_cordata")
    assert not species_verdict(linden, _ctx_of(heat=2.6), RULEBOOK, PARAMS).allowed
    assert species_verdict(linden, _ctx_of(heat=5.6), RULEBOOK, PARAMS).allowed


@pytest.mark.parametrize("code", ["cotinus_coggygria", "forsythia_ovata", "weigela_florida"])
def test_zone_five_species_need_an_explicit_regional_profile(code: str) -> None:
    """Скумпия, форзиция и вейгела есть в паспортах пилота, но по зоне в Москве подмерзают."""
    species = CATALOG.get(code)
    assert not species_verdict(species, _ctx_of(), RULEBOOK, PARAMS).allowed
    warmer = replace(PARAMS, region_hardiness_zone=5)
    assert species_verdict(species, _ctx_of(), RULEBOOK, warmer).allowed
