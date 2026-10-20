"""Чертёж совсем без подземных сетей: посадки с пометкой «требует согласования», а не отказ.

Сторонние входы (17.10.2026): пустой участок и тупик сторонний вход, Китай-город и ВДНХ
сторонний вход - ни одного слоя сетей (проверено по таблице слоёв и всем объектам модели). Строгий
профиль отказывал во всех местах, план выходил пустым. Решение пользователя 17.10.2026: сажать с
пометкой и записью «Исправлено автоматически»; прежний отказ - require_utility_data=true.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import LineString, box

from green.application.params import PlanParams
from green.application.placement import GreedyPlantingStrategy
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import Verdict
from green.infrastructure.config.repositories import (
    YamlProfileSource,
    YamlRuleBookSource,
    YamlSpeciesCatalog,
)

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULES = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
TREE = YamlSpeciesCatalog(CONFIG / "species.yaml").get("tilia_cordata")
NOTE = "Исправлено автоматически: в чертеже нет подземных сетей"


def _site(*, gas: bool = False) -> list[Feature]:
    def feature(cls: ObjectClass, geometry: object, name: str) -> Feature:
        return Feature(SourceRef("00000000", "00000000", name), name, geometry, object_class=cls)  # type: ignore[arg-type]

    items = [
        feature(ObjectClass.WORK_BOUNDARY, box(0, 0, 100, 50), "boundary"),
        feature(ObjectClass.LAWN, box(0, 12, 100, 50), "lawn"),
        feature(ObjectClass.CURB, LineString([(0, 10), (100, 10)]), "curb"),
    ]
    if gas:
        items.append(feature(ObjectClass.UTILITY_GAS, LineString([(0, 45), (100, 45)]), "gas"))
    return items


def test_drawing_without_utilities_plants_with_approval_and_a_note() -> None:
    plan = GreedyPlantingStrategy().plan(_site(), [], RULES, TREE, PlanParams())
    assert plan.placements
    assert {p.verdict for p in plan.placements} == {Verdict.NEEDS_APPROVAL}
    assert any(w.startswith(NOTE) for w in plan.warnings)


def test_refusal_stays_available_by_parameter() -> None:
    plan = GreedyPlantingStrategy().plan(
        _site(), [], RULES, TREE, PlanParams(require_utility_data=True)
    )
    assert not plan.placements
    assert not any(w.startswith(NOTE) for w in plan.warnings)


def test_drawing_with_utilities_is_checked_as_before() -> None:
    plan = GreedyPlantingStrategy().plan(_site(gas=True), [], RULES, TREE, PlanParams())
    assert plan.placements
    assert Verdict.ALLOWED in {p.verdict for p in plan.placements}
    assert not any(w.startswith(NOTE) for w in plan.warnings)


@pytest.mark.parametrize("profile", ["strict", "shrubs", "review", "barriers"])
def test_profiles_do_not_refuse_a_drawing_without_utilities(profile: str) -> None:
    params = YamlProfileSource(CONFIG / "profiles").load(profile, {})
    assert params.require_utility_data is False
