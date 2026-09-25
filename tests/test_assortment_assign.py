"""Назначение видов: однородность структур, квоты, существующие деревья, режимы, детерминизм."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from importlib import import_module
from itertools import product
from random import Random
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest

from green.application.assortment.assign import (
    GREEDY,
    MILP,
    Assignment,
    Candidate,
    Quotas,
    _repair_mixed_rows,
    assign,
)
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


# Двенадцать видов в разных родах и семействах: меньше десяти видов правило 10-20-30
# выдержать не может в принципе, и назначение честно оставило бы места пустыми.
CODES = (
    "tilia_cordata",
    "acer_platanoides",
    "ulmus_laevis",
    "sorbus_aucuparia",
    "betula_alba",
    "quercus_robur",
    "fraxinus_excelsior",
    "aesculus_hippocastanum",
    "malus_baccata",
    "prunus_padus",
    "picea_abies",
    "thuja_occidentalis",
)
CONIFERS = {"picea_abies": "Pinaceae", "thuja_occidentalis": "Cupressaceae"}
CATALOG = {code: _species(code, conifer=code in CONIFERS) for code in CODES}
CATALOG["thuja_occidentalis"] = replace(CATALOG["thuja_occidentalis"], family="Cupressaceae")
SCORES = {code: round(0.95 - 0.05 * position, 2) for position, code in enumerate(CODES)}


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


def _counts(result: Assignment) -> Counter[str]:
    return Counter(result.species_by_placement.values())


def test_each_row_gets_exactly_one_species_when_the_quota_allows() -> None:
    """Десять рядов по десять: 10% от ста - ровно ряд, аллеи однородны."""
    structures = _rows(10, 10)
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    assert result.solver == MILP
    assert len(result.species_by_placement) == 100
    assert not result.quota_violations
    for structure in structures:
        used = {result.species_by_placement[p] for p in structure.placement_ids}
        assert len(used) == 1, structure.structure_id


def test_rows_that_do_not_fit_the_quota_are_split_not_overfilled() -> None:
    """Три ряда по десять: 10% от тридцати - три дерева, ряд одним видом не выдержать."""
    structures = _rows(3, 10)
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    counts = _counts(result)
    assert len(result.species_by_placement) == 30
    assert max(counts.values()) <= 3
    assert not result.quota_violations
    assert result.split_placements


@pytest.mark.parametrize(("alternative_score", "homogeneous"), [(0.95, True), (0.1, False)])
def test_final_occupancy_can_make_a_row_species_quota_feasible(
    alternative_score: float, *, homogeneous: bool
) -> None:
    """The first pass sees 9 places; filling the tenth permits two trees of one species."""
    codes = ["S", "T", "U", *(f"F{i}" for i in range(6))]
    catalog = {code: _species(code) for code in codes}
    structures = [
        Structure("A", "row", ("a1", "a2")),
        Structure("B", "row", ("b1", "b2")),
        *(Structure(f"F{i}", "single", (f"f{i}",)) for i in range(6)),
    ]
    candidates = [
        Candidate(place, "A", "row", catalog[code], score)
        for place in ("a1", "a2")
        for code, score in (("S", 1.0), ("T", alternative_score))
    ]
    candidates.extend(
        [
            Candidate("b1", "B", "row", catalog["S"], 1.0),
            Candidate("b2", "B", "row", catalog["U"], 1.0),
        ]
    )
    candidates.extend(
        Candidate(f"f{i}", f"F{i}", "single", catalog[f"F{i}"], 1.0) for i in range(6)
    )
    params = replace(
        PARAMS, quota_species=0.2, quota_genus=1.0, quota_family=1.0, conifer_share=(0, 1)
    )
    result = assign(candidates, structures, catalog, {}, params)
    assert len(result.species_by_placement) == 10
    assert not result.quota_violations
    assert (result.species_by_placement["a1"] == result.species_by_placement["a2"]) is homogeneous
    assert ("a1" in result.split_placements) is not homogeneous
    assert {"b1", "b2"} <= result.split_placements


def test_row_repair_preserves_fill_quotas_and_each_rows_dominance() -> None:
    random = Random(9641)  # noqa: S311 - deterministic compatibility patterns
    codes = [f"species-{i}" for i in range(6)]
    catalog = {code: _species(code) for code in codes}
    params = replace(
        PARAMS, quota_species=0.3, quota_genus=1.0, quota_family=1.0, conifer_share=(0, 1)
    )
    quotas = Quotas(catalog, {}, params)
    places = [f"p-{i}" for i in range(10)]
    rows = {"row-1": places[:4], "row-2": places[4:8]}
    chosen = {place: codes[i % 5] for i, place in enumerate(places)}
    for _ in range(60):
        candidates = []
        for i, place in enumerate(places):
            row_id = "row-1" if i < 4 else "row-2" if i < 8 else f"single-{i}"
            kind = "row" if i < 8 else "single"
            compatible = {chosen[place], *random.sample(codes, random.randint(1, 4))}
            candidates.extend(
                Candidate(place, row_id, kind, catalog[code], random.random())
                for code in sorted(compatible)
            )
        result = _repair_mixed_rows(chosen, candidates, quotas)
        assert set(result) == set(chosen)
        assert not quotas.violations(result)
        for members in rows.values():
            before = max(Counter(chosen[place] for place in members).values())
            after = max(Counter(result[place] for place in members).values())
            assert after >= before


def test_quota_limits_a_species_when_structures_are_small() -> None:
    structures = _singles(30)
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    assert len(result.species_by_placement) == 30
    assert max(_counts(result).values()) <= 3
    assert not result.quota_violations


def test_existing_trees_consume_the_quota_and_push_the_species_out() -> None:
    """20 существующих лип и 20 новых мест: доля липы на улице уже выбрана, липы не будет."""
    structures = _singles(20)
    candidates = _candidates(structures, list(CATALOG))
    result = assign(candidates, structures, CATALOG, {"tilia_cordata": 20}, PARAMS)
    assert "tilia_cordata" not in set(result.species_by_placement.values())
    assert len(result.species_by_placement) == 20
    assert not result.quota_violations
    assert any("tilia_cordata" in note for note in result.notes)


def test_exhausted_species_does_not_block_one_other_plant() -> None:
    """Доля считается от занятых мест, а не от числа всех доступных точек."""
    structures = _singles(30)
    candidates = _candidates(structures, ["tilia_cordata", "acer_platanoides"])
    result = assign(candidates, structures, CATALOG, {"tilia_cordata": 20}, PARAMS)
    assert list(result.species_by_placement.values()) == ["acer_platanoides"]
    assert not result.quota_violations


def test_one_compatible_species_can_fill_one_of_many_available_places() -> None:
    structures = _singles(30)
    candidates = _candidates(structures, ["tilia_cordata"])
    result = assign(candidates, structures, CATALOG, {}, PARAMS)
    assert list(result.species_by_placement.values()) == ["tilia_cordata"]
    assert not result.quota_violations


def test_sparse_assignments_match_exhaustive_maximum_fill() -> None:
    """A seeded mix of unfamiliar compatibility patterns guards against fixture fitting."""
    random = Random(7342)  # noqa: S311 - deterministic test cases, not secrets
    structures = _singles(5)
    candidates = _candidates(structures, list(CATALOG))
    quotas = Quotas(CATALOG, {}, PARAMS)
    for _ in range(100):
        options = [random.sample(list(CATALOG), random.randint(1, 5)) for _ in structures]
        allowed = {
            structure.placement_ids[0]: set(codes)
            for structure, codes in zip(structures, options, strict=True)
        }
        usable = [
            candidate
            for candidate in candidates
            if candidate.species.code in allowed[candidate.placement_id]
        ]
        result = assign(usable, structures, CATALOG, {}, PARAMS)
        maximum = 0
        for selection in product(*(("", *codes) for codes in options)):
            chosen = {
                structure.placement_ids[0]: code
                for structure, code in zip(structures, selection, strict=True)
                if code
            }
            if not quotas.violations(chosen):
                maximum = max(maximum, len(chosen))
        assert len(result.species_by_placement) == maximum
        assert not result.quota_violations


def test_a_tiny_site_may_hold_one_plant_of_a_species() -> None:
    """Пять мест, доля 10% - половина растения: один экземпляр вида квоту не нарушает."""
    structures = _singles(5)
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    assert len(result.species_by_placement) == 5
    assert max(_counts(result).values()) == 1
    assert not result.quota_violations


def test_every_quota_holds_on_the_final_plan() -> None:
    structures = [*_rows(4, 10), *_singles(17)]
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    planned = len(result.species_by_placement)
    assert planned == 57
    assert not Quotas(CATALOG, {}, PARAMS).violations(result.species_by_placement)
    for code, count in _counts(result).items():
        assert count <= max(1, int(0.1 * planned)), code


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


def test_greedy_solver_keeps_rows_homogeneous_and_quotas_hard() -> None:
    structures = _rows(10, 10)
    params = replace(PARAMS, assortment_solver="greedy")
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, params)
    assert result.solver == GREEDY
    assert any("жадным" in note for note in result.notes)
    assert not result.quota_violations
    assert len(result.species_by_placement) >= 90
    for structure in structures:
        used = {
            result.species_by_placement[p]
            for p in structure.placement_ids
            if p in result.species_by_placement
        }
        assert len(used) <= 1


def test_greedy_leaves_places_empty_when_existing_trees_eat_every_quota() -> None:
    structures = _rows(1, 10)
    params = replace(PARAMS, assortment_solver="greedy")
    candidates = _candidates(structures, ["tilia_cordata"])
    result = assign(candidates, structures, CATALOG, {"tilia_cordata": 400}, params)
    assert result.species_by_placement == {}
    assert not result.quota_violations


def test_the_same_input_gives_the_same_assignment() -> None:
    structures = _rows(3, 10)
    candidates = _candidates(structures, list(CATALOG))
    first = assign(candidates, structures, CATALOG, {}, PARAMS)
    second = assign(list(reversed(candidates)), structures, CATALOG, {}, PARAMS)
    assert first.species_by_placement == second.species_by_placement


def test_no_candidates_give_an_empty_assignment() -> None:
    assert assign([], [], CATALOG, {}, PARAMS).species_by_placement == {}


def test_invalid_solver_primal_falls_back_to_checked_greedy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def invalid_primal(*_args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(x=np.full(len(cast("np.ndarray", kwargs["c"])), 0.6), success=True)

    monkeypatch.setattr(
        import_module("green.application.assortment.assign"), "milp", invalid_primal
    )
    structures = _singles(10)
    result = assign(_candidates(structures, list(CATALOG)), structures, CATALOG, {}, PARAMS)
    assert result.solver == GREEDY
    assert not result.quota_violations


def test_greedy_fallback_stays_close_to_the_solver_and_holds_quotas() -> None:
    """Запасной путь ищет наибольшее число мест T, при котором допуски от T выдержаны.

    Прежний вариант срезал превышения по одной посадке и терял больше половины плана
    (Берзарина: 110 мест против 280 у решателя).
    """
    structures = [*_rows(4, 10), *_singles(17)]
    candidates = _candidates(structures, list(CATALOG))
    solved = assign(candidates, structures, CATALOG, {}, PARAMS)
    greedy = assign(
        candidates, structures, CATALOG, {}, replace(PARAMS, assortment_solver="greedy")
    )
    assert not greedy.quota_violations
    assert len(greedy.species_by_placement) >= 0.9 * len(solved.species_by_placement)
