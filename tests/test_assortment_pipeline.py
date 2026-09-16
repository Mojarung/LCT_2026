"""Проход подбора целиком: карточка у каждой посадки, однородность рядов, сводка."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from green.application.assortment import assign_species
from green.application.assortment.context import site_context
from green.application.assortment.scoring import percent, score_species
from green.application.explain import explain
from green.application.params import PlanParams
from green.application.placement import MODE_LABELS
from green.domain.norms import PlantingType
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Placement, Plan, RuleCheck, Verdict
from green.infrastructure.config.repositories import YamlRuleBookSource, YamlSpeciesCatalog

CONFIG = Path(__file__).resolve().parents[1] / "config"
RULEBOOK = YamlRuleBookSource(CONFIG / "acts.yaml", CONFIG / "rules.yaml").load()
CATALOG = YamlSpeciesCatalog(CONFIG / "species.yaml")
DEFAULT = CATALOG.get("tilia_cordata")
PARAMS = PlanParams()
ALLEY = MODE_LABELS["alley"]
LAWN = MODE_LABELS["lawn"]

CHECKS = (
    RuleCheck("R-CURB-TREE-001", CheckOutcome.PASS, 2.0, 2.5, None, ObjectClass.CURB),
    RuleCheck("R-BLD-TREE-001", CheckOutcome.PASS, 5.0, 14.0, None, ObjectClass.BUILDING),
    # Теплосеть рядом: правило по роду (липа и клён 2 м, берёза и тополь 4 м) здесь решает,
    # поэтому попадает в объяснение. На тридцати метрах оно уже не основание, а шум.
    RuleCheck("R-HEAT-TREE-001", CheckOutcome.PASS, 2.0, 5.0, None, ObjectClass.UTILITY_HEAT),
)


def _placement(number: int, x: float, y: float, note: str) -> Placement:
    return Placement(
        placement_id=f"p-{number:03d}",
        number=number,
        planting_type=PlantingType.TREE,
        species=DEFAULT,
        x=x,
        y=y,
        verdict=Verdict.ALLOWED,
        checks=CHECKS,
        notes=(note,),
    )


def _plan() -> Plan:
    placements = []
    number = 1
    for row in range(2):
        for i in range(10):
            placements.append(_placement(number, i * 6.0, row * 100.0, ALLEY))
            number += 1
    for group in range(2):
        for i in range(8):
            placements.append(
                _placement(number, 300.0 + group * 60.0 + i % 4 * 3.0, i // 4 * 3.0, LAWN)
            )
            number += 1
    for single in range(4):
        placements.append(_placement(number, 600.0 + single * 80.0, 500.0, LAWN))
        number += 1
    return Plan(placements=tuple(placements), rejections=())


def test_every_placement_gets_a_card_and_rows_stay_homogeneous() -> None:
    plan = assign_species(_plan(), RULEBOOK, CATALOG.all(), PARAMS)
    assert len(plan.placements) == 40
    for placement in plan.placements:
        assert placement.assortment is not None
        assert placement.assortment.status in {"assigned", "no_species"}
    rows = {}
    for placement in plan.placements:
        info = placement.assortment
        assert info is not None
        if info.structure_kind == "row":
            rows.setdefault(info.structure_id, set()).add(placement.species.code)
    assert rows
    for structure_id, codes in rows.items():
        assert len(codes) == 1, structure_id


def test_percent_matches_the_score_of_the_chosen_species() -> None:
    plan = assign_species(_plan(), RULEBOOK, CATALOG.all(), PARAMS)
    checked = 0
    for placement in plan.placements:
        info = placement.assortment
        assert info is not None
        if info.status != "assigned":
            continue
        ctx = site_context(
            placement, structure_id=info.structure_id, structure_kind=info.structure_kind
        )
        assert percent(score_species(placement.species, ctx, PARAMS)) == info.percent
        checked += 1
    assert checked > 0


def test_alternatives_are_ranked_and_exclude_the_chosen_species() -> None:
    plan = assign_species(_plan(), RULEBOOK, CATALOG.all(), PARAMS)
    for placement in plan.placements:
        info = placement.assortment
        assert info is not None
        codes = [alternative.code for alternative in info.alternatives]
        assert placement.species.code not in codes or info.status == "no_species"
        assert len(codes) == len(set(codes))
        percents = [alternative.percent for alternative in info.alternatives]
        assert percents == sorted(percents, reverse=True)
        assert len(codes) <= 3


def test_summary_counts_add_up_and_the_plan_is_not_a_monoculture() -> None:
    plan = assign_species(_plan(), RULEBOOK, CATALOG.all(), PARAMS)
    summary = plan.assortment_summary
    assert summary is not None
    assigned = sum(1 for p in plan.placements if p.assortment and p.assortment.status == "assigned")
    assert sum(summary.counts.values()) == assigned
    assert summary.no_species == 40 - assigned
    assert len(summary.counts) > 1
    assert summary.shannon > 0
    assert abs(sum(summary.genus_shares.values()) - 1.0) < 1e-6
    assert set(summary.decor_by_month) == set(range(1, 13))
    assert summary.solver in {"milp", "greedy"}


def test_rejected_species_are_counted_by_ground_so_nothing_is_dropped_silently() -> None:
    plan = assign_species(_plan(), RULEBOOK, CATALOG.all(), PARAMS)
    summary = plan.assortment_summary
    assert summary is not None
    assert summary.rejected_by_kind
    assert sum(summary.rejected_by_kind.values()) > 0
    assert any(rule.startswith("R-") for rule in summary.rejected_by_rule)


def test_single_mode_keeps_the_profile_species_but_still_scores_it() -> None:
    params = replace(PARAMS, assortment_mode="single")
    plan = assign_species(_plan(), RULEBOOK, CATALOG.all(), params)
    assert {p.species.code for p in plan.placements} == {DEFAULT.code}
    for placement in plan.placements:
        assert placement.assortment is not None
        assert placement.assortment.status == "single"
        assert placement.assortment.percent > 0
    summary = plan.assortment_summary
    assert summary is not None
    assert summary.counts == {DEFAULT.code: 40}


def test_existing_trees_change_the_outcome() -> None:
    plan = assign_species(_plan(), RULEBOOK, CATALOG.all(), PARAMS)
    chosen = {p.species.code for p in plan.placements if p.assortment}
    crowded = assign_species(
        _plan(), RULEBOOK, CATALOG.all(), PARAMS, existing=dict.fromkeys(chosen, 40)
    )
    summary = crowded.assortment_summary
    assert summary is not None
    assert summary.existing
    assert set(summary.counts) != chosen


def test_explanation_names_the_species_percent_factors_and_alternatives() -> None:
    plan = explain(assign_species(_plan(), RULEBOOK, CATALOG.all(), PARAMS), RULEBOOK)
    texts = {e.subject_id: e.text for e in plan.explanations}
    assert len(texts) == 40
    for placement in plan.placements:
        info = placement.assortment
        assert info is not None
        text = texts[placement.placement_id]
        assert "Вид" in text
        if info.status == "assigned":
            assert placement.species.name_ru in text
            assert f"({info.percent}%" in text
            assert "оценка по факторам" in text
        if info.alternatives:
            assert "Альтернативы:" in text
            assert info.alternatives[0].name_ru in text


def test_explanation_carries_the_rule_id_for_a_species_dependent_norm() -> None:
    """У вида с правилом по роду в объяснении стоит идентификатор правила и цитата акта."""
    plan = explain(assign_species(_plan(), RULEBOOK, CATALOG.all(), PARAMS), RULEBOOK)
    texts = {e.subject_id: e.text for e in plan.explanations}
    with_rule = [
        texts[p.placement_id]
        for p in plan.placements
        if p.assortment and any(r.rule_id for r in p.assortment.reasons if r.kind == "norm")
    ]
    assert with_rule
    assert any("R-HEAT-TREE-00" in text for text in with_rule)
    assert any("МГСН" in text for text in with_rule)


def test_an_empty_plan_is_returned_untouched() -> None:
    plan = assign_species(Plan(placements=(), rejections=()), RULEBOOK, CATALOG.all(), PARAMS)
    assert plan.placements == ()
    assert plan.assortment_summary is not None
