"""Видовые нормы в режиме одного вида: недопустимый вид останавливает прогон до размещения."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from green.application.errors import InputError
from green.application.params import PlanParams
from green.application.placement import GreedyPlantingStrategy
from green.application.species_norms import species_norms
from green.infrastructure.config.repositories import YamlRuleBookSource, YamlSpeciesCatalog

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
CATALOG = YamlSpeciesCatalog(CONFIG / "species.yaml")
SINGLE = replace(PlanParams(), assortment_mode="single", zones=False)


@pytest.mark.parametrize(
    ("code", "rule_id"),
    [
        ("acer_negundo", "R-INV-ACERNEG-001"),
        ("populus_balsamifera", "R-PPSEVEN-FLUFF-001"),
        ("betula_pendula", "R-PPSEVEN-ALLERGEN-001"),
    ],
)
def test_single_mode_refuses_a_species_forbidden_by_norms(code: str, rule_id: str) -> None:
    with pytest.raises(InputError, match=rule_id):
        GreedyPlantingStrategy().plan((), (), RULEBOOK, CATALOG.get(code), SINGLE)


def test_auto_mode_leaves_species_norms_to_the_assortment_stage() -> None:
    """В режиме подбора вид профиля задаёт только отступы по роду: запрет решает подбор."""
    auto = replace(SINGLE, assortment_mode="auto")
    plan = GreedyPlantingStrategy().plan((), (), RULEBOOK, CATALOG.get("betula_pendula"), auto)
    assert plan.placements == ()


def test_group_three_on_protected_land_is_refused_in_single_mode() -> None:
    protected = replace(SINGLE, territory="protected_green")
    with pytest.raises(InputError, match="R-INV-PHYSOC-001"):
        GreedyPlantingStrategy().plan(
            (), (), RULEBOOK, CATALOG.get("physocarpus_opulifolius"), protected
        )


def test_ordinary_species_passes_without_conditions() -> None:
    norms = species_norms(CATALOG.get("tilia_cordata"), RULEBOOK, "green_fund")
    assert norms.blocking is None
    assert norms.reasons == ()


def test_condition_is_printed_in_the_explanation() -> None:
    from green.application.explain import _reason  # noqa: PLC0415 - частная функция шаблона

    norms = species_norms(CATALOG.get("amelanchier_spicata"), RULEBOOK, "green_fund")
    assert norms.blocking is None
    (reason,) = norms.reasons
    text = _reason(reason)
    assert "R-INVGROUP-THREE-001" in text
    assert "условие: меры по недопущению распространения" in text
