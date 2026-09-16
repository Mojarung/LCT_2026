"""Назначение видов: однородность структур, квоты, существующие деревья, режимы, детерминизм."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

from green.application.assortment.assign import GREEDY, MILP, Candidate, assign
from green.application.assortment.structures import Structure
from green.application.params import PlanParams
from green.domain.planting import LifeForm, Species

PARAMS = PlanParams()


def _species(code: str, *, conifer: bool = False, genus: str | None = None) -> Species:
    return Species(
        code=code,
        name_ru=code,
        name_lat=f"{code.capitalize()} test",
        crown_diameter_m=3.0,
        genus=genus or code,
        family="Pinaceae" if conifer else f"{code.capitalize()}aceae",
        life_form=LifeForm.TREE_MEDIUM,
        height_m=12.0,
        crown_mature_m=4.0,
        hardiness_zone=3,
        salt_tolerance=1,
        sources={"hardiness_zone": "справочник", "salt_tolerance": "справочник"},
    )


CATALOG = {
    code: _species(code, conifer=code in {"picea_abies", "pinus_sylvestris"})
    for code in (
        "tilia_cordata",
        "acer_platanoides",
        "ulmus_laevis",
        "sorbus_aucuparia",
        "picea_abies",
        "pinus_sylvestris",
    )
}
SCORES = {
    "tilia_cordata": 0.90,
    "acer_platanoides": 0.80,
    "ulmus_laevis": 0.70,
    "sorbus_aucuparia": 0.60,
    "picea_abies": 0.50,
    "pinus_sylvestris": 0.40,
}


def _rows(count: int, size: int) -> list[Structure]:
    return [
        Structure(
            structure_id=f"row-{r + 1}",
            kind="row",
            placement_ids=tuple(f"p-{r * size + i:03d}" for i in range(size)),
        )
        for r in range(count)
    ]


def _singles(count: int) -> list[Structure]:
    return [
        Structure(structure_id=f"single-{i}", kind="single", placement_ids=(f"s-{i:03d}",))
        for i in range(count)
    ]


def _candidates(structures: list[Structure], codes: list[str]) -> list[Candidate]:
    return [
        Candidate(
            placement_id=placement_id,
            structure_id=structure.structure_id,
            structure_kind=structure.kind,
            species=CATALOG[code],
            score=SCORES[code],
        )
        for structure in structures
        for placement_id in structure.placement_ids
        for code in codes
    ]


def test_each_row_gets_exactly_one_species() -> None:
    structures = _rows(3, 10)
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    assert result.solver == MILP
    assert len(result.species_by_placement) == 30
    for structure in structures:
        used = {result.species_by_placement[p] for p in structure.placement_ids}
        assert len(used) == 1, structure.structure_id


def test_rows_do_not_all_take_the_best_species() -> None:
    structures = _rows(3, 10)
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    counts = Counter(result.species_by_placement.values())
    assert len(counts) == 3
    assert max(counts.values()) == 10


def test_quota_limits_a_species_when_structures_are_small() -> None:
    structures = _singles(30)
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    assert result.solver == MILP
    assert len(result.species_by_placement) == 30
    counts = Counter(result.species_by_placement.values())
    # Шесть видов на 30 посадок: доля 10% - это три дерева на вид, то есть 18 мест из 30.
    # Квота мягкая, поэтому все 30 заняты, а превышение на 12 показано пофамильно, а не
    # спрятано пустыми посадками.
    assert max(counts.values()) <= 6
    assert len(counts) >= 5
    assert result.quota_violations
    assert all("отклонение от квоты" in violation for violation in result.quota_violations)


def test_existing_trees_consume_the_quota_and_push_the_species_out() -> None:
    """20 существующих лип и 20 новых мест: доля липы в популяции уже выбрана, липы не будет."""
    structures = _singles(20)
    candidates = _candidates(structures, list(CATALOG))
    result = assign(candidates, structures, CATALOG, {"tilia_cordata": 20}, PARAMS)
    assert "tilia_cordata" not in set(result.species_by_placement.values())
    assert len(result.species_by_placement) == 20


def test_exhausted_diversity_leaves_places_empty_instead_of_piling_on_one_species() -> None:
    """Два вида, из них один уже занимает свою долю по виду, роду и семейству.

    Сервис заполняет столько, сколько позволяет разнообразие, и оставляет остальное пустым,
    а не досаживает вид, которого на улице и так больше нормы. Пустые места видны в сводке.
    """
    structures = _singles(30)
    candidates = _candidates(structures, ["tilia_cordata", "acer_platanoides"])
    result = assign(candidates, structures, CATALOG, {"tilia_cordata": 20}, PARAMS)
    counts = Counter(result.species_by_placement.values())
    assert counts["tilia_cordata"] == 0
    assert 0 < len(result.species_by_placement) < 30
    assert result.quota_violations


def test_given_mode_reproduces_the_requested_counts() -> None:
    structures = _rows(3, 10)
    params = replace(
        PARAMS,
        assortment_mode="given",
        given_assortment={"picea_abies": 20, "tilia_cordata": 10},
    )
    candidates = _candidates(structures, ["picea_abies", "tilia_cordata"])
    result = assign(candidates, structures, CATALOG, {}, params)
    counts = Counter(result.species_by_placement.values())
    assert counts == Counter({"picea_abies": 20, "tilia_cordata": 10})


def test_given_counts_are_an_upper_bound_and_the_shortfall_is_reported() -> None:
    """Участок берётся не целиком, но и не делится: 25 лип на рядах по 10 дают 25, а не 20.

    Ряд из двух видов сервис не делает, поэтому остаток может не влезть; тогда прогон
    говорит, какого вида и на сколько не хватило, вместо молчаливого недобора.
    """
    structures = _rows(4, 10)
    params = replace(
        PARAMS,
        assortment_mode="given",
        given_assortment={"tilia_cordata": 25, "picea_abies": 15},
    )
    candidates = _candidates(structures, ["tilia_cordata", "picea_abies"])
    result = assign(candidates, structures, CATALOG, {}, params)
    counts = Counter(result.species_by_placement.values())
    assert counts["tilia_cordata"] == 25
    assert counts["picea_abies"] <= 15
    assert sum(counts.values()) >= 35
    for structure in structures:
        used = {
            result.species_by_placement[p]
            for p in structure.placement_ids
            if p in result.species_by_placement
        }
        assert len(used) <= 1, structure.structure_id
    if sum(counts.values()) < 40:
        assert any("не хватило" in note for note in result.notes)


def test_conifer_share_is_respected_when_conifers_are_available() -> None:
    structures = _singles(40)
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    conifers = sum(1 for code in result.species_by_placement.values() if CATALOG[code].is_conifer)
    low, high = PARAMS.conifer_share
    assert low * 40 <= conifers <= high * 40


def test_conifer_lower_bound_is_dropped_with_a_note_when_no_conifer_fits() -> None:
    structures = _singles(10)
    deciduous = [c for c in CATALOG if not CATALOG[c].is_conifer]
    result = assign(_candidates(structures, deciduous), structures, CATALOG, {}, PARAMS)
    assert len(result.species_by_placement) == 10
    assert any("хвойн" in note for note in result.notes)


def test_greedy_solver_can_be_chosen_and_keeps_rows_homogeneous() -> None:
    structures = _rows(3, 10)
    params = replace(PARAMS, assortment_solver="greedy")
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, params)
    assert result.solver == GREEDY
    assert any("жадным" in note for note in result.notes)
    for structure in structures:
        used = {result.species_by_placement[p] for p in structure.placement_ids}
        assert len(used) == 1


def test_greedy_reports_a_violation_when_existing_trees_eat_every_quota() -> None:
    structures = _rows(1, 10)
    params = replace(PARAMS, assortment_solver="greedy")
    candidates = _candidates(structures, ["tilia_cordata"])
    result = assign(candidates, structures, CATALOG, {"tilia_cordata": 400}, params)
    assert result.quota_violations
    assert len(result.species_by_placement) == 10


def test_the_same_input_gives_the_same_assignment() -> None:
    structures = _rows(3, 10)
    candidates = _candidates(structures, list(CATALOG))
    first = assign(candidates, structures, CATALOG, {}, PARAMS)
    second = assign(list(reversed(candidates)), structures, CATALOG, {}, PARAMS)
    assert first.species_by_placement == second.species_by_placement


def test_no_candidates_give_an_empty_assignment() -> None:
    assert assign([], [], CATALOG, {}, PARAMS).species_by_placement == {}
