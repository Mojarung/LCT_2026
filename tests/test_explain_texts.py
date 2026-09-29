"""Тексты объяснений для дендролога: норма таблицы и прирост за крону, вклад в индекс словами,
подпись месяцев декоративности в сводке состава."""

from __future__ import annotations

import re

from green.application.assortment.assign import Assignment
from green.application.assortment.summary import build_summary
from green.application.explain import describe_check, describe_value, explain
from green.domain.norms import (
    Act,
    Citation,
    CitationStatus,
    DistanceRule,
    MeasureTo,
    PlantingType,
    RuleBook,
    Severity,
)
from green.domain.objects import ObjectClass
from green.domain.planting import (
    CheckOutcome,
    LifeForm,
    Placement,
    Plan,
    Rejection,
    RuleCheck,
    Species,
    Verdict,
)
from green.domain.quality import PlantingValue
from green.infrastructure.reports.artifacts import _assortment_summary
from green.infrastructure.reports.interpretation_report import (
    _how,
    _placement_row,
    _rejection_row,
    _Rules,
)

SP42 = Act("SP42_13330_2016", "СП 42.13330.2016", "ред.", "https://x", short="СП 42.13330.2016")


def _rule(rule_id: str, cls: ObjectClass, base: float, clause: str) -> DistanceRule:
    return DistanceRule(
        rule_id,
        cls,
        PlantingType.TREE,
        base,
        MeasureTo.EDGE,
        Severity.FORBID,
        Citation("SP42_13330_2016", clause, "", CitationStatus.VERIFIED),
    )


CURB = _rule("R-CURB-T", ObjectClass.CURB, 2.0, "п. 9.6, табл. 9.1: край проезжей части")
HEAT = _rule("R-HEAT-T", ObjectClass.UTILITY_HEAT, 2.0, "п. 9.6, табл. 9.1: тепловая сеть")
THORN = _rule("R-THORN-T", ObjectClass.PAVEMENT_EDGE, 2.0, "п. 9.22: колючие растения")
BOOK = RuleBook(acts={SP42.act_id: SP42}, distance_rules=(CURB, HEAT, THORN), fingerprint="test")
# Крона 7 м: прирост 1,00 м при 0,5 м на метр сверх 5 м - прирост и ставка различимы.
LIME = Species(
    "lime", "Липа", "Tilia cordata", 5.0, life_form=LifeForm.TREE_MEDIUM, crown_mature_m=7.0
)
SPIREA = Species(
    "spirea", "Спирея", "Spiraea", 1.0, life_form=LifeForm.SHRUB_MEDIUM, decor_months=frozenset()
)


def _check(rule: DistanceRule, threshold: float, measured: float) -> RuleCheck:
    outcome = CheckOutcome.PASS if measured >= threshold else CheckOutcome.FAIL
    return RuleCheck(rule.rule_id, outcome, threshold, measured, None, rule.object_class)


def _placement(*checks: RuleCheck, species: Species = LIME) -> Placement:
    return Placement("p-1", 1, PlantingType.TREE, species, 0.0, 0.0, Verdict.ALLOWED, checks)


# --- Норма таблицы и прирост за крону -------------------------------------------------------


def test_threshold_raised_for_the_crown_names_the_table_norm_and_the_increment() -> None:
    text = describe_check(_check(CURB, 3.0, 3.40), BOOK, crown_m=7.0)
    assert text.startswith(
        "до бортового камня 3,40 м ≥ 3,00 м: 2,00 м по табл. 9.1 и 1,00 м за крону 7 м "
        "(R-CURB-T: СП 42.13330.2016, п. 9.6, табл. 9.1"
    )


def test_a_violation_of_a_raised_threshold_names_both_parts_too() -> None:
    text = describe_check(_check(HEAT, 3.0, 2.40), BOOK, crown_m=7.0)
    assert text.startswith(
        "до теплосети 2,40 м < 3,00 м: 2,00 м по табл. 9.1 и 1,00 м за крону 7 м (R-HEAT-T:"
    )


def test_without_the_crown_the_increment_is_named_by_its_condition() -> None:
    """Отказ и проверка точки вида не знают: прирост назван условием примечания."""
    text = describe_check(_check(CURB, 3.0, 2.40), BOOK)
    assert "< 3,00 м: 2,00 м по табл. 9.1 и 1,00 м за крону шире 5 м (R-CURB-T:" in text


def test_threshold_equal_to_the_table_reads_as_before() -> None:
    text = describe_check(_check(CURB, 2.0, 3.40), BOOK, crown_m=7.0)
    assert text == (
        "до бортового камня 3,40 м ≥ 2,00 м (R-CURB-T: СП 42.13330.2016, п. 9.6, табл. 9.1: "
        "край проезжей части)"
    )


def test_a_rule_outside_table_9_1_gets_no_crown_increment_wording() -> None:
    """Прим. 1 относится к табл. 9.1: у другого правила разница порогов прироста не значит."""
    text = describe_check(_check(THORN, 2.5, 3.40), BOOK, crown_m=7.0)
    assert text == (
        "до границы покрытия 3,40 м ≥ 2,50 м (R-THORN-T: СП 42.13330.2016, п. 9.22: колючие "
        "растения)"
    )


def test_placement_explanation_calls_the_increment_a_project_interpretation_once() -> None:
    placement = _placement(_check(CURB, 3.0, 3.40), _check(HEAT, 3.0, 4.10))
    text = explain(Plan(placements=(placement,), rejections=()), BOOK).explanations[0].text
    assert text.count("за крону 7 м") == 2
    sentence = (
        " Прирост за крону - по прим. 1 к табл. 9.1 СП 42.13330.2016; его величину акт не "
        "задаёт, 0,5 м на метр кроны сверх 5 м - толкование проекта (crown_extra_per_m)."
    )
    assert text.count(sentence) == 1


def test_placement_without_increment_has_no_interpretation_sentence() -> None:
    placement = _placement(_check(CURB, 2.0, 3.40))
    text = explain(Plan(placements=(placement,), rejections=()), BOOK).explanations[0].text
    assert "за крону" not in text
    assert "толкование проекта" not in text


def test_rejection_names_the_increment_without_a_rate_it_cannot_know() -> None:
    rejection = Rejection(
        "r-1", 1, PlantingType.TREE, 0.0, 0.0, Verdict.FORBIDDEN, (_check(CURB, 3.0, 2.40),)
    )
    text = explain(Plan(placements=(), rejections=(rejection,)), BOOK).explanations[0].text
    assert "1,00 м за крону шире 5 м" in text
    assert text.endswith(
        " Прирост за крону - по прим. 1 к табл. 9.1 СП 42.13330.2016; его величину акт не "
        "задаёт, прирост - толкование проекта (crown_extra_per_m)."
    )


def test_governing_norm_cell_shows_the_table_norm_and_the_increment() -> None:
    row = _placement_row(_placement(_check(CURB, 3.0, 3.40)), _Rules(BOOK))
    assert row[8] == "3,00 = 2,00 + 1,00 за крону"


def test_rejection_row_shows_the_increment_of_the_broken_norm() -> None:
    rejection = Rejection(
        "r-1", 1, PlantingType.TREE, 0.0, 0.0, Verdict.FORBIDDEN, (_check(CURB, 3.0, 2.40),)
    )
    row = _rejection_row(rejection, _Rules(BOOK))
    assert row[5] == "до бортового камня: 2,40 м < 3,00 м = 2,00 + 1,00 за крону (R-CURB-T)"


def test_placements_intro_names_the_increment_basis_only_when_there_is_one() -> None:
    raised = Plan(placements=(_placement(_check(CURB, 3.0, 3.40)),), rejections=())
    plain = Plan(placements=(_placement(_check(CURB, 2.0, 3.40)),), rejections=())
    assert "толкование проекта (crown_extra_per_m)" in _how(raised, _Rules(BOOK))
    assert "прим. 1 к табл. 9.1" not in _how(plain, _Rules(BOOK))


def test_governing_norm_cell_without_increment_is_a_number() -> None:
    row = _placement_row(_placement(_check(CURB, 2.0, 3.40)), _Rules(BOOK))
    assert row[8] == "2,00"


# --- Вклад в индекс словами -----------------------------------------------------------------


def _value(delta: float, *, flagged: bool = False, percentile: float = 0.0) -> PlantingValue:
    return PlantingValue("p-1", delta, {}, ("тень",), flagged=flagged, percentile=percentile)


def test_contribution_is_points_of_a_hundred_not_permille() -> None:
    text = describe_value(_value(0.00089, percentile=0.96))
    assert text == (
        " Ценность: повышает индекс качества плана на 0,089 пункта из 100, больше, чем у 96% "
        "посадок плана: тень."
    )


def test_a_round_contribution_drops_the_trailing_zero() -> None:
    assert "на 0,09 пункта из 100" in describe_value(_value(0.0009))


def test_a_weak_place_says_whether_it_lowers_the_index() -> None:
    text = describe_value(_value(-0.00042, flagged=True))
    assert text.startswith(" Слабое место (снижает индекс качества плана на 0,042 пункта из 100):")


def test_a_weak_place_with_a_positive_contribution_says_it_raises() -> None:
    text = describe_value(_value(0.00031, flagged=True))
    assert text.startswith(" Слабое место (повышает индекс качества плана на 0,031 пункта из 100):")


def test_a_negative_contribution_names_how_much_higher_the_index_is_without_it() -> None:
    text = describe_value(_value(-0.00042))
    assert text.startswith(
        " Ценность: без этой посадки расчётный индекс выше на 0,042 пункта из 100"
    )


def test_a_contribution_near_zero_reads_as_before() -> None:
    text = describe_value(_value(0.000004))
    assert text.startswith(" Ценность: вклад в индекс качества около нуля")


def test_no_permille_sign_in_any_contribution_text() -> None:
    texts = [
        describe_value(_value(delta, flagged=flagged))
        for delta in (0.00089, -0.00042, 0.000004)
        for flagged in (False, True)
    ]
    assert not [t for t in texts if "‰" in t]
    assert all(re.search(r"пункта из 100|около нуля", t) for t in texts)


# --- Подпись месяцев декоративности в сводке состава ----------------------------------------


def _summary_of(*species: Species) -> dict[str, object]:
    catalog = {s.code: s for s in species}
    assignment = Assignment(
        species_by_placement={f"p-{i}": s.code for i, s in enumerate(species)}, solver="test"
    )
    summary = build_summary(
        assignment,
        catalog,
        {},
        mode="auto",
        no_species=0,
        rejected_by_kind={},
        rejected_by_rule={},
    )
    return _assortment_summary(summary)


def test_decor_months_of_trees_are_labelled_as_trees_only() -> None:
    payload = _summary_of(LIME)
    assert payload.get("decor_by_month_of") == "tree"
    note = str(payload.get("decor_by_month_note"))
    assert note.startswith("Месяцы декоративности деревьев")
    assert "Кустарники здесь не считаются" in note
    assert "«Сезонность» считает деревья и кустарники вместе" in note


def test_decor_months_of_shrubs_are_labelled_as_shrubs_only() -> None:
    payload = _summary_of(SPIREA)
    assert payload.get("decor_by_month_of") == "shrub"
    note = str(payload.get("decor_by_month_note"))
    assert note.startswith("Месяцы декоративности кустарников")
    assert "Деревья здесь не считаются" in note


def test_decor_months_of_a_mixed_summary_name_both() -> None:
    payload = _summary_of(LIME, SPIREA)
    assert payload.get("decor_by_month_of") == "mixed"
    assert str(payload.get("decor_by_month_note")).startswith(
        "Месяцы декоративности деревьев и кустарников"
    )
