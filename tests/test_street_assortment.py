"""Улица у сетей: сколько пород деревьев проходит нормы и рекомендовано ассортиментом Москвы.

Прогон 16-17.10.2026: у борта и кабеля оставалось 3-4 породы (рябина, клён Гиннала, сосна
горная), а туя и боярышник обыкновенный в ассортименте Москвы для дорог помечены «-». Каталог
дополнен породами, которые рекомендуют и МГСН 1.02-02 (табл. В.6, «улиц и дорог» «+»), и
ассортимент Москвы для магистралей и улиц: клён татарский, боярышник полумягкий, рябина
промежуточная. Приёмка задачи 13 плана финала - от 8 пород на улицу.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from green.application.assortment.context import SiteContext
from green.application.assortment.filters import off_assortment, species_verdict
from green.application.params import PlanParams
from green.domain.objects import ObjectClass
from green.infrastructure.config.repositories import YamlRuleBookSource, YamlSpeciesCatalog

ROOT = Path(__file__).resolve().parents[1]
RULEBOOK = YamlRuleBookSource(ROOT / "config/acts.yaml", ROOT / "config/rules.yaml").load()
CATALOG = YamlSpeciesCatalog(ROOT / "config/species.yaml")


def _tight_street() -> SiteContext:
    """Газон 5 м между бортом и тротуаром, силовой кабель и связь в 2,5 м."""
    clearance = {
        ObjectClass.CURB: 2.5,
        ObjectClass.SIDEWALK: 2.5,
        ObjectClass.UTILITY_POWER: 2.5,
        ObjectClass.UTILITY_TELECOM: 2.6,
        ObjectClass.BUILDING: 12.0,
    }
    return SiteContext("p-1", 0.0, 0.0, clearance, False, category="streets")


def _recommended_trees() -> list[str]:
    ctx = _tight_street()
    found = []
    for species in CATALOG.all():
        if not species.is_tree:
            continue
        verdict = species_verdict(species, ctx, RULEBOOK, PlanParams())
        if verdict.allowed and not off_assortment(verdict):
            found.append(species.code)
    return found


def test_tight_street_spot_has_at_least_five_recommended_tree_species() -> None:
    assert len(_recommended_trees()) >= 5, _recommended_trees()


@pytest.mark.parametrize("code", ["acer_tataricum", "crataegus_submollis", "sorbus_intermedia"])
def test_new_street_species_are_recommended_for_roads(code: str) -> None:
    species = CATALOG.get(code)
    assert species.mos_marks.get("roads") is True
    assert species.mos_ref
