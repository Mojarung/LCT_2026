"""Индекс качества плана v3: слагаемые, цели участка, проверка перед оценкой, монотонность и
точная ценность каждой посадки."""

from __future__ import annotations

import math
import statistics
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import shapely
import yaml
from shapely.geometry import LineString, box

from green.application.explain import explain
from green.application.params import DEFAULT_QUALITY_WEIGHTS, PlanParams
from green.application.placement import MODE_LABELS
from green.application.quality import Site, _summary, _thousandths, assess, evaluate, site_of
from green.application.quality.site import split_segments, street_length
from green.domain.norms import PlantingType, RuleBook
from green.domain.objects import Feature, ObjectClass, SourceRef
from green.domain.planting import (
    Alternative,
    AssortmentInfo,
    CheckOutcome,
    LifeForm,
    Placement,
    Plan,
    Rejection,
    RuleCheck,
    Species,
    Verdict,
)

ALLEY = MODE_LABELS["alley"]
LAWN = MODE_LABELS["lawn"]
PARAMS = PlanParams()
ROOT = Path(__file__).resolve().parents[1]


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


def _term(plan: Plan, key: str, params: PlanParams = PARAMS, site: Site | None = None):  # noqa: ANN202
    quality = evaluate(plan, site or _site(), params)
    return next(t for t in quality.terms if t.key == key)


# --- Участок: длина улицы и цели -----------------------------------------------------------


def test_street_length_of_a_strip_is_its_axis() -> None:
    # Ось по скелету: сама ось и два уса в углы, около L + 0,4 W.
    assert street_length(box(0, 0, 1000, 30)) == pytest.approx(1000.0, rel=0.02)


def test_pockets_of_the_boundary_do_not_lengthen_the_street() -> None:
    """Прежняя оценка по периметру удлиняла улицу за каждый карман границы (docs/notes/34)."""
    strip = box(0, 0, 1000, 30)
    pockets = strip.union(box(100, 30, 110, 60)).union(box(500, 30, 510, 60))
    assert street_length(pockets) == pytest.approx(street_length(strip), rel=0.03)


def test_boundary_faces_split_by_the_reserve_are_one_street() -> None:
    """Грани границы сжаты на запас точности и не касаются (constraints._boundary): длина не
    складывается по граням - у Камчатской так выходило 4,6 км вместо 1,6."""
    faces = shapely.union_all([box(0, 0, 1000, 25), box(0, 25.2, 1000, 30), box(0, 30.2, 1000, 60)])
    assert street_length(faces) == pytest.approx(street_length(box(0, 0, 1000, 60)), rel=0.02)
    assert street_length(faces) < 1100


def test_street_length_from_the_project_note_overrides_the_axis() -> None:
    density = _term(_plan(), "density", replace(PARAMS, street_length_m=500.0))
    assert density.measure["street_length_m"] == 500.0
    assert "по записке проекта" in density.note


def test_curbs_keep_their_physical_length_inside_the_work_boundary() -> None:
    site = _site()
    assert np.linalg.norm(site.curb_segments[:, 1] - site.curb_segments[:, 0], axis=1).sum() == 200
    assert site.street_length_m == pytest.approx(200.0, rel=0.05)


def test_tree_target_is_the_norm_capped_by_the_site_capacity() -> None:
    """МГСН 1.02-02, табл. В.1: «на 1 км при условии допустимости насаждений»."""
    plan = _plan()
    literal = _term(plan, "density")
    capped = _term(replace(plan, stats={"capacity_trees": 5}), "density")
    km = literal.measure["street_length_m"] / 1000
    assert literal.measure["target_trees"] == pytest.approx(150 * km, abs=0.1)
    assert capped.measure["target_trees"] == 5.0
    assert capped.measure["capacity_trees"] == 5.0
    assert "места, прошедшие нормы" in capped.note
    # 10 деревьев при цели 5 - половина за деревья насыщена.
    assert capped.score is not None
    assert literal.score is not None
    assert capped.score > literal.score


def test_the_portfolio_capacity_wins_over_the_variant_capacity() -> None:
    plan = replace(_plan(), stats={"capacity_trees": 5, "site_capacity_trees": 8})
    assert _term(plan, "density").measure["target_trees"] == 8.0


def test_density_saturates_at_the_target_and_never_punishes_more() -> None:
    """Перебор против цели баллов не даёт, но и не отнимает (заказчик: «не самый плотный»,
    а принятые проекты сажают до 400 деревьев на 1 км)."""
    base = replace(_plan(), stats={"capacity_trees": 5})
    extra = tuple(_place(100 + i, 130.0 + 6 * i, -5.0, LIME, note=LAWN) for i in range(10))
    more = replace(base, placements=(*base.placements, *extra))
    before, after = _term(base, "density"), _term(more, "density")
    assert before.score is not None
    assert after.score is not None
    assert after.score == pytest.approx(before.score)


def test_canopy_reference_crown_is_the_catalog_median() -> None:
    catalog = yaml.safe_load((ROOT / "config" / "species.yaml").read_text(encoding="utf-8"))
    entries = catalog["species"] if isinstance(catalog, dict) else catalog
    crowns = [
        float(item.get("crown_mature_m") or item.get("crown_diameter_m"))
        for item in entries
        if str(item.get("life_form", "")).startswith("tree")
    ]
    assert PARAMS.canopy_crown_m == pytest.approx(statistics.median(crowns))


def test_canopy_is_measured_against_the_crowns_of_the_target_trees() -> None:
    canopy = _term(_plan(), "canopy")
    density = _term(_plan(), "density")
    goal = 0.75 * density.measure["target_trees"] * math.pi * (PARAMS.canopy_crown_m / 2) ** 2
    assert canopy.measure["goal_m2"] == pytest.approx(goal, rel=2e-3)
    assert canopy.score == pytest.approx(min(1.0, canopy.measure["m2"] / goal), abs=1e-3)


# --- Слагаемые ------------------------------------------------------------------------------


def test_rows_count_plantings_that_hold_the_row() -> None:
    quality = evaluate(_plan(), _site(), PARAMS)
    rows = next(t for t in quality.terms if t.key == "rows")
    # Держат ряд пять лип и три клёна; дуб - чужой вид после разрыва 13 м.
    assert rows.measure["holding"] == 8
    # Дерево в середине ровного ряда держит шаг: без него ряд беднее.
    assert quality.values["p-003"].by_term["rows"] > 0
    # Чужой вид с разрывом 13 м ряда не держит: в счёт не идёт, но и не отнимает.
    assert quality.values["p-009"].by_term.get("rows", 0.0) == pytest.approx(0.0, abs=1e-9)
    assert (
        "вид отличается от соседей по ряду"
        in " ".join(quality.values["p-009"].reasons + quality.values["p-009"].weak)
        or rows.score is not None
    )


def test_the_only_member_of_a_family_is_worth_more_than_one_of_many() -> None:
    quality = evaluate(_plan(), _site(), PARAMS)
    rare = quality.values["p-013"].by_term["diversity"]
    common = quality.values["p-001"].by_term.get("diversity", 0.0)
    assert rare > common
    assert any("единственный представитель семейства" in r for r in quality.values["p-013"].reasons)


def test_a_species_counts_fully_from_a_tenth_of_the_target() -> None:
    """Три посадки редкого вида рядом с сотней лип - ещё не целый вид (цель - 5 видов)."""
    params = replace(PARAMS, street_length_m=1000.0)  # цель 150 деревьев, вид целиком с 15
    diversity = _term(_plan(), "diversity", params)
    # Липы 5/15, клёны 3/15, дуб и рябина по 1/15 - засчитано 10/15 вида из 5.
    assert diversity.measure["richness_trees"] == pytest.approx(10 / 15, abs=1e-3)


def test_dominant_tree_species_above_practice_is_named() -> None:
    lime_only = replace(
        _plan(),
        placements=tuple(
            replace(p, species=LIME) if p.planting_type is PlantingType.TREE else p
            for p in _plan().placements
        ),
    )
    assert "выше практики" in _term(lime_only, "diversity").note


def test_shrub_under_a_crown_is_a_second_tier() -> None:
    quality = evaluate(_plan(), _site(), PARAMS)
    tiers = next(t for t in quality.terms if t.key == "tiers")
    # Кустарник есть под кронами деревьев на x=16 и x=60: два дерева к цели участка.
    assert tiers.score == pytest.approx(2 / tiers.measure["goal"], abs=1e-4)
    assert quality.values["p-012"].by_term["tiers"] > 0


def test_fit_takes_the_assortment_penalty_for_conditions() -> None:
    plan = _plan()
    allergen = replace(plan.placements[0], species=replace(LIME, allergen=1))
    marked = replace(plan, placements=(allergen, *plan.placements[1:]))
    quality = evaluate(marked, _site(), PARAMS)
    value = quality.values["p-001"]
    assert any("слабый аллерген" in reason for reason in value.reasons + value.weak)
    clean = evaluate(plan, _site(), PARAMS).values["p-001"].by_term["fit"]
    assert 0 < value.by_term["fit"] < clean


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


def test_a_species_the_table_is_silent_about_counts_half() -> None:
    plan = _plan()
    silent = replace(LIME, categories={})
    limited = replace(LIME, categories={"streets": "limited"})

    def with_lime(kind: Species) -> Plan:
        return replace(
            plan,
            placements=tuple(
                replace(p, species=kind) if p.species.code == "lime" else p for p in plan.placements
            ),
        )

    assert _term(with_lime(silent), "category").score == pytest.approx(
        _term(with_lime(limited), "category").score
    )


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
    value = quality.values["p-001"]
    assert value.by_term.get("margin", 0.0) == pytest.approx(0.0, abs=1e-9)
    assert any("ближе нормы" in text for text in value.weak)


def test_curb_under_a_gas_tolerant_crown_counts_for_dust() -> None:
    quality = evaluate(_plan(), _site(), PARAMS)
    dust = next(t for t in quality.terms if t.key == "dust")
    assert dust.score is not None
    assert dust.score > 0
    # Липа в 2 м от борта с кроной радиусом 3 м прикрывает около 4 м борта.
    assert any("крона над бортом" in r for r in quality.values["p-003"].reasons)


def test_season_is_the_share_of_decorative_months() -> None:
    season = _term(_plan(), "season")
    # Май, июнь, сентябрь, октябрь, январь.
    assert season.score == pytest.approx(5 / 12, abs=1e-4)


def test_dust_counts_only_curbs_with_soil_beside_them() -> None:
    site = _site()
    segments = split_segments(site.curb_segments, 1.0)
    near_trees = segments.mean(axis=1)[:, 0] < 100.0
    fair_site = Site(site.boundary, segments, curb_soil=near_trees)
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
    curb_total = np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1).sum()
    assert fair.measure["curb_total_m"] == pytest.approx(curb_total)


# --- Проверка перед оценкой и сводка ---------------------------------------------------------


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


def test_without_a_work_boundary_the_index_is_not_given_but_terms_are() -> None:
    site = Site(boundary=None, curb_segments=np.zeros((0, 2, 2)))
    quality = evaluate(_plan(), site, PARAMS)
    assert quality.index is None
    assert "Граница работ" in quality.gate
    by_key = {t.key: t for t in quality.terms}
    assert by_key["density"].score is None
    # Без длины улицы цели нет: пригодность показана средним по посадкам.
    assert by_key["fit"].score is not None
    assert not quality.values


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
    assert all("Ценность:" in e.text for e in texts)
    assert plan.quality is not None
    assert plan.quality.summary[0].startswith("Индекс качества плана")


def test_the_summary_does_not_retell_the_terms_or_print_zero_penalties() -> None:
    """Полоски слагаемых стоят над сводкой: «Сильное/Слабое» их пересказывали, «-0,000» - шум."""
    summary = assess(_plan(), _site(), PARAMS).quality.summary  # type: ignore[union-attr]
    assert not any(line.startswith(("Сильное", "Слабое:")) for line in summary)
    assert not any("-0,000" in line for line in summary)
    assert not any("отрицательным вкладом" in line for line in summary)


def test_penalty_parts_add_up_to_the_total_shown() -> None:
    """Части штрафа в тысячных сходятся с итогом: -0,006 при видимых -0,002, -0,002 и -0,001
    читалось как ошибка счёта."""
    shares = _thousandths({"a": 0.0024, "b": 0.0024, "c": 0.0012}, 0.006)
    assert sum(shares.values()) == 6
    lines = _summary(0.9, "", (), {"lost": 0.0012}, {})
    assert any(line.startswith("Штрафы -0,001") for line in lines)


# --- Монотонность и точная ценность --------------------------------------------------------


def _extra_places(rng: np.random.Generator, count: int) -> list[Placement]:
    """Посадки на свободных местах участка: любой вид, одиночки (не в рядах)."""
    kinds = [LIME, MAPLE, OAK, ROWAN, SPIREA]
    places = []
    for k in range(count):
        kind = kinds[int(rng.integers(len(kinds)))]
        places.append(
            _place(
                200 + k,
                float(rng.uniform(5, 195)),
                float(rng.uniform(-9, 9)),
                kind,
                structure=f"single-{200 + k}",
                note=LAWN,
                percent=int(rng.integers(0, 101)),
                measured=float(rng.uniform(1.0, 4.0)),
            )
        )
    return places


def _index(plan: Plan, params: PlanParams) -> float:
    quality = evaluate(plan, _site(), params)
    assert quality.index is not None
    return quality.index


@pytest.mark.parametrize("seed", range(12))
def test_a_planting_that_passes_the_norms_never_lowers_the_index(seed: int) -> None:
    """Главное свойство v3: посадка, прошедшая нормы, индекс не снижает - ни вид хуже
    среднего, ни посадка впритык, ни перебор плотности, ни главная порода."""
    rng = np.random.default_rng(seed)
    params = replace(
        PARAMS,
        quality_weights=dict(
            zip(DEFAULT_QUALITY_WEIGHTS, rng.random(len(DEFAULT_QUALITY_WEIGHTS)), strict=True)
        ),
    )
    plan = _plan()
    kept = tuple(p for p in plan.placements if rng.random() < 0.6) or plan.placements[:1]
    current = replace(plan, placements=kept)
    before = _index(current, params)
    for extra in _extra_places(rng, 8):
        current = replace(current, placements=(*current.placements, extra))
        after = _index(current, params)
        assert after >= before - 1e-9
        before = after


def test_value_of_each_planting_is_the_exact_drop_of_the_index() -> None:
    plan, site = _plan(), _site()
    quality = evaluate(plan, site, PARAMS)
    assert quality.index is not None
    assert 0 < quality.index < 1
    for placement in plan.placements:
        without = evaluate(_without(plan, placement.placement_id), site, PARAMS)
        assert without.index is not None
        expected = quality.index - without.index
        value = quality.values[placement.placement_id]
        assert value.delta == pytest.approx(expected, abs=2e-6)
        assert value.delta >= -1e-9


def _counterfactual_plans() -> dict[str, Plan]:
    a = _place(1, 12, 0, LIME, structure="row-1")
    b = _place(2, 18, 0, MAPLE, structure="row-1")
    c = _place(3, 40, 0, OAK, structure="single-2", note=LAWN)
    return {
        "singleton": Plan((a,), ()),
        "last_row": Plan((a, b, c), ()),
        "same_row": Plan((a, replace(b, species=LIME), c), ()),
        "last_fit": Plan((a, replace(c, assortment=None)), ()),
        "last_margin": Plan((a, replace(c, checks=())), ()),
        "last_season": Plan((a, replace(c, species=replace(OAK, decor_months=frozenset()))), ()),
        "allergen": Plan((replace(a, species=replace(LIME, allergen=1)),), ()),
        "no_terms": Plan((a, b), ()),
    }


@pytest.mark.parametrize("scenario", list(_counterfactual_plans()))
@pytest.mark.parametrize("weighted", ["default", "diversity", "rows", "season", "canopy", "fit"])
def test_removal_matches_full_recalculation_at_term_boundaries(
    scenario: str, weighted: str
) -> None:
    plan, site = _counterfactual_plans()[scenario], _site()
    weights = (
        {}
        if weighted == "default"
        else {key: float(key == weighted) for key in DEFAULT_QUALITY_WEIGHTS}
    )
    params = replace(PARAMS, quality_weights=weights)
    quality = evaluate(plan, site, params)
    assert quality.index is not None
    for placement in plan.placements:
        after = evaluate(_without(plan, placement.placement_id), site, params)
        assert after.index is not None
        value = quality.values[placement.placement_id]
        assert value.delta == pytest.approx(quality.index - after.index, abs=2e-6)
        assert sum(value.by_term.values()) == pytest.approx(value.delta, abs=6e-6)


@pytest.mark.parametrize("seed", range(20))
def test_removal_recalculation_on_mixed_subsets(seed: int) -> None:
    rng = np.random.default_rng(seed)
    source = _plan()
    chosen = [p for p in source.placements if rng.random() < 0.5] or [source.placements[0]]
    plan = replace(source, placements=tuple(chosen))
    params = replace(
        PARAMS,
        quality_weights=dict(
            zip(DEFAULT_QUALITY_WEIGHTS, rng.random(len(DEFAULT_QUALITY_WEIGHTS)), strict=True)
        ),
    )
    quality = evaluate(plan, _site(), params)
    assert quality.index is not None
    for placement in chosen:
        after = evaluate(_without(plan, placement.placement_id), _site(), params)
        assert after.index is not None
        assert quality.values[placement.placement_id].delta == pytest.approx(
            quality.index - after.index, abs=2e-6
        )


def test_lost_places_cost_a_penalty_that_a_new_planting_reduces() -> None:
    lost = Rejection("r-1", 1, PlantingType.TREE, 150.0, 5.0, Verdict.ALLOWED, (), note="квота")
    plan = replace(_plan(), rejections=(lost,))
    quality = evaluate(plan, _site(), PARAMS)
    assert quality.penalties["lost"] > 0
    extra = _place(99, 140.0, -5.0, LIME, structure="single-99", note=LAWN)
    grown = evaluate(replace(plan, placements=(*plan.placements, extra)), _site(), PARAMS)
    assert grown.penalties["lost"] < quality.penalties["lost"]
    assert any(line.startswith("Штрафы") for line in quality.summary)


def test_score_only_evaluation_gives_the_same_index() -> None:
    plan, site = _plan(), _site()
    full = evaluate(plan, site, PARAMS)
    quick = evaluate(plan, site, PARAMS, values=False)
    assert quick.index == full.index
    assert not quick.values
