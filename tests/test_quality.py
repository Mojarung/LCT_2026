"""Индекс качества плана: слагаемые, проверка перед оценкой и ценность каждой посадки."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from shapely.geometry import LineString, box

from green.application.explain import explain
from green.application.params import DEFAULT_QUALITY_WEIGHTS, PlanParams
from green.application.placement import MODE_LABELS
from green.application.quality import Site, assess, evaluate, site_of
from green.application.quality.site import street_length
from green.application.quality.terms import fork
from green.domain.norms import PlantingType, RuleBook
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import (
    Alternative,
    AssortmentInfo,
    CheckOutcome,
    LifeForm,
    Placement,
    Plan,
    RuleCheck,
    Species,
    Verdict,
)

ALLEY = MODE_LABELS["alley"]
LAWN = MODE_LABELS["lawn"]
PARAMS = PlanParams()


def _species(  # noqa: PLR0913 - карточка вида для теста
    code: str,
    genus: str,
    family: str,
    *,
    tree: bool = True,
    crown: float = 6.0,
    gas: int = 2,
    category: str = "plus",
    decor: frozenset[int] = frozenset({5, 6}),
) -> Species:
    return Species(
        code,
        code,
        code,
        crown,
        genus=genus,
        family=family,
        life_form=LifeForm.TREE_MEDIUM if tree else LifeForm.SHRUB_MEDIUM,
        gas_tolerance=gas,
        categories={"streets": category} if category else {},
        decor_months=decor,
    )


LIME = _species("lime", "tilia", "Malvaceae")
MAPLE = _species("maple", "acer", "Sapindaceae", decor=frozenset({9, 10}))
OAK = _species("oak", "quercus", "Fagaceae", category="limited")
ROWAN = _species("rowan", "sorbus", "Rosaceae", category="", decor=frozenset({1, 5}))
SPIREA = _species("spirea", "spiraea", "Rosaceae", tree=False, crown=1.5, gas=1)
CODES = ("lime", "maple", "oak", "rowan", "spirea")


def _place(  # noqa: PLR0913 - посадка для теста
    number: int,
    x: float,
    y: float,
    species: Species,
    *,
    structure: str | None = None,
    note: str = ALLEY,
    percent: int = 80,
    measured: float | None = None,
) -> Placement:
    kind = None
    if structure is not None:
        kind = structure.split("-")[0]
    shrub = species.life_form is LifeForm.SHRUB_MEDIUM
    return Placement(
        placement_id=f"p-{number:03d}",
        number=number,
        planting_type=PlantingType.SHRUB if shrub else PlantingType.TREE,
        species=species,
        x=x,
        y=y,
        verdict=Verdict.ALLOWED,
        checks=(
            RuleCheck(
                "R-TEST-001",
                CheckOutcome.PASS,
                threshold_m=2.0,
                measured_m=measured if measured is not None else 2.0 + 0.05 * number,
                object_class=ObjectClass.UTILITY_WATER,
            ),
        ),
        notes=(note,),
        assortment=AssortmentInfo(
            status="assigned",
            percent=percent,
            factors={},
            structure_id=structure,
            structure_kind=kind,
            # Все виды теста допустимы любому месту: цель по числу видов от удаления не меняется.
            alternatives=tuple(Alternative(c, c, 50, "оценка ниже") for c in CODES),
        ),
    )


def _plan() -> Plan:
    first = [_place(1 + i, 10.0 + 6.0 * i, 0.0, LIME, structure="row-1") for i in range(5)]
    second = [
        _place(6, 60.0, 0.0, MAPLE, structure="row-2"),
        _place(7, 66.0, 0.0, MAPLE, structure="row-2"),
        _place(8, 72.0, 0.0, MAPLE, structure="row-2"),
        _place(9, 85.0, 0.0, OAK, structure="row-2", percent=60),
    ]
    shrubs = [
        _place(10, 16.5, 1.0, SPIREA, structure="group-3", note="группа кустарников"),
        _place(11, 17.0, -1.0, SPIREA, structure="group-3", note="группа кустарников"),
        _place(12, 61.0, 1.0, SPIREA, structure="group-3", note="группа кустарников"),
    ]
    lone = [_place(13, 120.0, 5.0, ROWAN, structure="single-4", note=LAWN, percent=70)]
    return Plan(placements=(*first, *second, *shrubs, *lone), rejections=())


def _site() -> Site:
    boundary = box(0.0, -10.0, 200.0, 10.0)
    curb = LineString([(0.0, -2.0), (200.0, -2.0)])
    features = [
        Feature(
            SourceRef("f", "x", "1"), "граница", boundary, object_class=ObjectClass.WORK_BOUNDARY
        ),
        Feature(SourceRef("f", "x", "2"), "борт", curb, object_class=ObjectClass.CURB),
    ]
    return site_of(features)


def _without(plan: Plan, placement_id: str) -> Plan:
    return replace(
        plan, placements=tuple(p for p in plan.placements if p.placement_id != placement_id)
    )


def test_street_length_of_a_strip_is_its_axis() -> None:
    assert street_length(box(0, 0, 1000, 30)) == pytest.approx(1000.0)


def test_an_upper_bound_of_density_proves_shortage_but_not_excess() -> None:
    assert fork(900, 600, 720, excess=False) == 1.0
    assert fork(300, 600, 720, excess=False) == pytest.approx(0.5)


def test_fork_rewards_the_norm_and_punishes_both_sides() -> None:
    assert fork(75, 150, 180) == pytest.approx(0.5)
    assert fork(165, 150, 180) == 1.0
    assert fork(360, 150, 180) == pytest.approx(0.5)
    assert fork(600, 150, 180) == 0.0


def test_curbs_are_sampled_by_metre_inside_the_work_boundary() -> None:
    site = _site()
    assert len(site.curb_points) == 200
    assert site.street_length_m == pytest.approx(200.0, rel=0.01)


def test_value_of_each_planting_is_the_exact_drop_of_the_index() -> None:
    plan, site = _plan(), _site()
    quality = evaluate(plan, site, PARAMS)
    assert quality.index is not None
    assert 0 < quality.index < 1
    for placement in plan.placements:
        without = evaluate(_without(plan, placement.placement_id), site, PARAMS)
        assert without.index is not None
        expected = quality.index - without.index
        assert quality.values[placement.placement_id].delta == pytest.approx(expected, abs=2e-6)


def test_rows_want_one_species_and_an_even_step() -> None:
    quality = evaluate(_plan(), _site(), PARAMS)
    rows = next(t for t in quality.terms if t.key == "rows")
    # Первый ряд идеален, во втором чужой вид и разрыв 13 м.
    assert rows.score is not None
    assert 0.5 < rows.score < 1
    # Дерево в середине ровного ряда держит шаг: без него в ряду разрыв 12 м.
    assert quality.values["p-003"].by_term["rows"] > 0
    # Чужой вид с разрывом 13 м ряд портит: без него ряд лучше.
    assert quality.values["p-009"].by_term["rows"] < 0


def test_the_only_member_of_a_family_is_worth_more_than_one_of_many() -> None:
    quality = evaluate(_plan(), _site(), PARAMS)
    rare = quality.values["p-013"].by_term["diversity"]
    common = quality.values["p-001"].by_term["diversity"]
    assert rare > common
    assert any("единственный представитель семейства" in r for r in quality.values["p-013"].reasons)


def test_shrub_under_an_alley_crown_is_a_second_tier() -> None:
    quality = evaluate(_plan(), _site(), PARAMS)
    tiers = next(t for t in quality.terms if t.key == "tiers")
    # Кустарник есть под кронами деревьев на x=16 и x=60: два из девяти деревьев аллеи.
    assert tiers.score == pytest.approx(2 / 9, abs=1e-4)
    assert quality.values["p-012"].by_term["tiers"] > 0


def test_a_violation_closes_the_gate() -> None:
    plan = _plan()
    bad = replace(
        plan.placements[0],
        verdict=Verdict.FORBIDDEN,
        checks=(
            RuleCheck(
                "R-TEST-001",
                CheckOutcome.FAIL,
                threshold_m=2.0,
                measured_m=1.0,
                object_class=ObjectClass.UTILITY_WATER,
            ),
        ),
    )
    quality = evaluate(replace(plan, placements=(bad, *plan.placements[1:])), _site(), PARAMS)
    assert quality.index is None
    assert "нарушением норм: 1" in quality.gate


def test_a_soft_norm_on_approval_is_not_a_violation_but_has_no_margin() -> None:
    plan = _plan()
    soft = replace(
        plan.placements[0],
        verdict=Verdict.NEEDS_APPROVAL,
        checks=(
            RuleCheck(
                "R-TEST-001",
                CheckOutcome.FAIL,
                threshold_m=2.0,
                measured_m=1.5,
                object_class=ObjectClass.UTILITY_WATER,
            ),
        ),
    )
    quality = evaluate(replace(plan, placements=(soft, *plan.placements[1:])), _site(), PARAMS)
    assert quality.index is not None
    assert not quality.gate
    assert quality.values["p-001"].by_term["margin"] < 0


def test_shade_is_measured_against_the_zone_where_planting_is_allowed() -> None:
    plan = _plan()
    whole = {t.key: t for t in evaluate(plan, _site(), PARAMS).terms}["canopy"]
    zoned_plan = replace(plan, stats={"zone_allowed_m2": 400})
    zoned = {t.key: t for t in evaluate(zoned_plan, _site(), PARAMS).terms}["canopy"]
    assert whole.score is not None
    assert zoned.score is not None
    assert zoned.score > whole.score
    assert "допустима" in zoned.note


def test_without_a_work_boundary_the_index_is_not_given_but_terms_are() -> None:
    site = Site(boundary=None, curb_points=np.zeros((0, 2)))
    quality = evaluate(_plan(), site, PARAMS)
    assert quality.index is None
    assert "Граница работ" in quality.gate
    by_key = {t.key: t for t in quality.terms}
    assert by_key["density"].score is None
    assert by_key["fit"].score is not None


def test_species_not_recommended_for_streets_lowers_the_category() -> None:
    plan = _plan()
    good = evaluate(plan, _site(), PARAMS)
    minus = replace(LIME, categories={"streets": "minus"})
    worse = replace(
        plan,
        placements=tuple(
            replace(p, species=minus) if p.species.code == "lime" else p for p in plan.placements
        ),
    )
    bad = evaluate(worse, _site(), PARAMS)
    score = {t.key: t.score for t in good.terms}["category"]
    lowered = {t.key: t.score for t in bad.terms}["category"]
    assert score is not None
    assert lowered is not None
    assert lowered < score
    assert bad.index is not None
    assert good.index is not None
    assert bad.index < good.index


def test_profile_names_only_the_weights_it_changes() -> None:
    params = PlanParams(quality_weights={"season": 0.0})
    quality = evaluate(_plan(), _site(), params)
    weights = {t.key: t.weight for t in quality.terms}
    assert weights["season"] == 0
    assert weights["density"] > DEFAULT_QUALITY_WEIGHTS["density"]
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-3)


def test_value_goes_into_the_explanation_and_the_stats() -> None:
    plan = assess(_plan(), _site(), PARAMS)
    assert "quality_index" in plan.stats
    texts = explain(plan, RuleBook(acts={}, distance_rules=(), fingerprint="test")).explanations
    assert all("Ценность:" in e.text or "Слабое место" in e.text for e in texts)
    assert plan.quality is not None
    assert plan.quality.summary[0].startswith("Индекс качества плана")


def test_the_summary_does_not_retell_the_terms_or_print_zero_penalties() -> None:
    """Полоски слагаемых стоят над сводкой: «Сильное/Слабое» их пересказывали, «-0,000» - шум."""
    summary = assess(_plan(), _site(), PARAMS).quality.summary  # type: ignore[union-attr]
    assert not any(line.startswith(("Сильное", "Слабое:")) for line in summary)
    assert not any("-0,000" in line for line in summary)


def test_curb_under_a_gas_tolerant_crown_counts_for_dust() -> None:
    quality = evaluate(_plan(), _site(), PARAMS)
    dust = next(t for t in quality.terms if t.key == "dust")
    assert dust.score is not None
    assert dust.score > 0
    # Липа в 2 м от борта с кроной радиусом 3 м прикрывает около 4 м борта.
    assert any("крона над бортом" in r for r in quality.values["p-003"].reasons)


def test_a_species_the_table_is_silent_about_does_not_lower_the_category() -> None:
    plan = _plan()
    silent = replace(LIME, categories={})
    quiet = replace(
        plan,
        placements=tuple(
            replace(p, species=silent) if p.species.code == "lime" else p for p in plan.placements
        ),
    )
    before = {t.key: t.score for t in evaluate(plan, _site(), PARAMS).terms}["category"]
    after = {t.key: t.score for t in evaluate(quiet, _site(), PARAMS).terms}["category"]
    assert before is not None
    assert after is not None
    # Липы выпали из среднего; остались клёны и спиреи «+» и дуб «с огр.», и ни одна
    # посадка не получила штраф за молчание акта.
    assert after == pytest.approx((6 * 1.0 + 0.5) / 7, abs=1e-4)


def test_density_counts_only_what_the_admissible_zone_can_hold() -> None:
    """МГСН 1.02-02, табл. В.1: «на 1 км при условии допустимости насаждений»."""
    plan = replace(_plan(), stats={"zone_capacity_trees": 5})
    literal = replace(PARAMS, density_admissible=False)
    plain = {t.key: t for t in evaluate(plan, _site(), literal).terms}["density"]
    fair = {
        t.key: t for t in evaluate(plan, _site(), replace(PARAMS, density_admissible=True)).terms
    }["density"]
    assert plain.score is not None
    assert fair.score is not None
    # 10 деревьев на 200 м улицы - 50 на 1 км: против нормы 150 это треть, против вместимости
    # зоны (5 деревьев - 25 на 1 км) - полная норма.
    assert fair.score > plain.score
    assert fair.measure["trees_capacity_per_km"] == 25.0
    assert "допустимости" in fair.note


def test_dust_counts_only_curbs_with_soil_beside_them() -> None:
    site = _site()
    near_trees = site.curb_points[:, 0] < 100.0
    fair_site = Site(site.boundary, site.curb_points, curb_soil=near_trees)
    plan = _plan()
    plain = {t.key: t for t in evaluate(plan, site, replace(PARAMS, dust_admissible=False)).terms}[
        "dust"
    ]
    fair = {
        t.key: t for t in evaluate(plan, fair_site, replace(PARAMS, dust_admissible=True)).terms
    }["dust"]
    assert plain.score is not None
    assert fair.score is not None
    assert fair.score > plain.score
    assert fair.measure["curb_total_m"] == len(site.curb_points)
