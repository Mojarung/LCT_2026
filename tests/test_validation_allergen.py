"""Проверка плана и подбор вида читают один и тот же приоритет акта по аллергенам: вид,
который подбор при allergen_act_priority=false не назначил бы, проверка тоже не пропускает."""

from __future__ import annotations

from test_assortment_filters import CATALOG, RULEBOOK

from green.application.params import PlanParams
from green.application.validation import validate_plan
from green.domain.norms import PlantingType
from green.domain.planting import Placement, Plan, Verdict

BIRCH = next(s for s in CATALOG.all() if s.code.startswith("betula"))


def _issues(params: PlanParams) -> list[str]:
    placement = Placement("p", 1, PlantingType.TREE, BIRCH, 0.0, 0.0, Verdict.ALLOWED, ())
    report = validate_plan(Plan(placements=(placement,), rejections=()), (), (), RULEBOOK, params)
    return [i.code for i in report.issues]


def test_mass_allergen_follows_the_profile_priority() -> None:
    base = PlanParams(require_soil=False, require_work_boundary=False, require_utility_data=False)
    assert BIRCH.allergen >= 2
    assert "species_rule" not in _issues(base)
    strict = PlanParams(
        require_soil=False,
        require_work_boundary=False,
        require_utility_data=False,
        allergen_act_priority=False,
    )
    assert "species_rule" in _issues(strict)
