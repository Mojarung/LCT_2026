"""Шаг между деревьями по взрослым кронам: вилка 743-ПП, подбор вида и проверка плана."""

from __future__ import annotations

from dataclasses import replace

import pytest

from green.application.assortment.assign import Candidate, assign
from green.application.assortment.spacing import (
    Neighbors,
    TreePair,
    crowded,
    enforce_spacing,
    tree_neighbors,
)
from green.application.params import PlanParams, tree_pair_min_m, tree_pair_step_m
from green.application.placement import MODE_ALLEY, MODE_LABELS, MODE_LAWN
from green.application.validation import _spacing
from green.domain.norms import PlantingType
from green.domain.planting import LifeForm, Placement, Species, Verdict

PARAMS = PlanParams()


def _species(code: str, crown: float) -> Species:
    return Species(
        code=code,
        name_ru=code,
        name_lat=f"{code.capitalize()} test",
        crown_diameter_m=3.0,
        genus=code,
        family=f"{code.capitalize()}aceae",
        life_form=LifeForm.TREE_MEDIUM,
        height_m=12.0,
        crown_mature_m=crown,
        hardiness_zone=3,
        salt_tolerance=1,
        sources={"hardiness_zone": "справочник", "salt_tolerance": "справочник"},
    )


SPRUCE = _species("picea", 8.0)
LIME = _species("tilia", 12.0)
HAWTHORN = _species("crataegus", 4.0)
ROWAN = _species("sorbus", 6.0)
CATALOG = {s.code: s for s in (SPRUCE, LIME, HAWTHORN, ROWAN)}


def _tree(pid: str, x: float, species: Species, mode: str = MODE_LAWN) -> Placement:
    return Placement(
        placement_id=pid,
        number=0,
        planting_type=PlantingType.TREE,
        species=species,
        x=x,
        y=0.0,
        verdict=Verdict.ALLOWED,
        checks=(),
        notes=(MODE_LABELS[mode],),
    )


@pytest.mark.parametrize(
    ("first", "second", "row", "step"),
    [
        (SPRUCE, SPRUCE, False, 6.0),  # кроны 8 м, смыкание 25%
        (LIME, LIME, False, 7.0),  # 9 м по кронам - верх вилки групповой посадки
        (HAWTHORN, HAWTHORN, False, 5.0),  # 3 м по кронам - низ вилки
        (SPRUCE, HAWTHORN, False, 5.0),
        (LIME, LIME, True, 5.0),  # ряд аллеи: spacing_m, полог аллеи смыкается
    ],
)
def test_pair_step_follows_crowns_inside_group_range(
    first: Species, second: Species, *, row: bool, step: float
) -> None:
    assert tree_pair_step_m(first, second, PARAMS, row=row) == pytest.approx(step)


def test_pair_step_off_is_one_step_for_all() -> None:
    params = replace(PARAMS, crown_spacing=False)
    assert tree_pair_step_m(LIME, LIME, params, row=False) == PARAMS.spacing_m


def test_tolerance_never_goes_below_tree_minimum() -> None:
    assert tree_pair_min_m(HAWTHORN, HAWTHORN, PARAMS, row=False) == pytest.approx(5.0)
    assert tree_pair_min_m(SPRUCE, SPRUCE, PARAMS, row=False) == pytest.approx(5.7)


def test_assignment_puts_compact_species_where_neighbours_are_close() -> None:
    # Два места в 5 м, оба предпочли бы ель или липу: вместе им тесно. Оба места заняты -
    # у одного крупный вид, у соседа компактный.
    candidates = [
        Candidate("a", "single-a", "single", SPRUCE, 0.9),
        Candidate("a", "single-a", "single", HAWTHORN, 0.5),
        Candidate("b", "single-b", "single", LIME, 0.9),
        Candidate("b", "single-b", "single", ROWAN, 0.5),
    ]
    neighbors = Neighbors((TreePair("a", "b", 5.0, row=False),), PARAMS)
    result = assign(candidates, [], CATALOG, {}, PARAMS, neighbors=neighbors)
    chosen = result.species_by_placement
    assert set(chosen) == {"a", "b"}
    big = {SPRUCE.code, LIME.code}
    assert sum(code in big for code in chosen.values()) == 1
    loser = next(pid for pid, code in chosen.items() if code not in big)
    assert "шаг по взрослым кронам" in next(iter(result.crowded[loser].values()))


def test_without_neighbours_both_take_the_big_species() -> None:
    candidates = [
        Candidate("a", "single-a", "single", SPRUCE, 0.9),
        Candidate("b", "single-b", "single", LIME, 0.9),
    ]
    result = assign(candidates, [], CATALOG, {}, PARAMS)
    assert result.species_by_placement == {"a": SPRUCE.code, "b": LIME.code}


def test_group_with_tight_inner_pairs_gets_no_tight_pair() -> None:
    candidates = [
        Candidate(pid, "group-1", "group", species, score)
        for pid in ("a", "b", "c")
        for species, score in ((SPRUCE, 0.9), (HAWTHORN, 0.4))
    ]
    pairs = (TreePair("a", "b", 5.0, row=False), TreePair("b", "c", 5.0, row=False))
    neighbors = Neighbors(pairs, PARAMS)
    chosen = assign(candidates, [], CATALOG, {}, PARAMS, neighbors=neighbors).species_by_placement
    assert list(chosen.values()).count(SPRUCE.code) < len(chosen) or len(chosen) < 2
    for pair in pairs:
        if pair.first in chosen and pair.second in chosen:
            first, second = CATALOG[chosen[pair.first]], CATALOG[chosen[pair.second]]
            assert not neighbors.conflict(first, second, pair.distance, row=pair.row)


def test_enforce_spacing_drops_lower_score_of_a_tight_pair() -> None:
    neighbors = Neighbors((TreePair("a", "b", 5.0, row=False),), PARAMS)
    kept = enforce_spacing(
        {"a": SPRUCE.code, "b": SPRUCE.code},
        neighbors,
        CATALOG,
        {("a", SPRUCE.code): 0.4, ("b", SPRUCE.code): 0.8},
    )
    assert kept == {"b": SPRUCE.code}


def test_crowded_names_neighbour_step_and_act() -> None:
    # Липа с кроной 12 м: ели рядом нужно 7 м, боярышнику - 5,7 м.
    neighbors = Neighbors((TreePair("a", "b", 5.8, row=False),), PARAMS)
    notes = crowded({"b": LIME.code}, {"a": [SPRUCE.code, HAWTHORN.code]}, neighbors, CATALOG)
    assert set(notes["a"]) == {SPRUCE.code}
    assert "743-ПП, табл. 3.6.2" in notes["a"][SPRUCE.code]


def test_neighbours_mark_alley_pairs_as_row() -> None:
    plan = [
        _tree("a", 0.0, LIME, MODE_ALLEY),
        _tree("b", 5.0, LIME, MODE_ALLEY),
        _tree("c", 10.0, LIME),
    ]
    neighbors = tree_neighbors(plan, PARAMS)
    assert neighbors is not None
    rows = {(p.first, p.second): p.row for p in neighbors.pairs}
    assert rows[("a", "b")] is True
    assert rows[("b", "c")] is False


def test_validation_checks_pair_step_by_crowns() -> None:
    tight = [_tree("a", 0.0, SPRUCE), _tree("b", 5.0, SPRUCE)]
    fine = [_tree("a", 0.0, HAWTHORN), _tree("b", 5.0, HAWTHORN)]
    alley = [_tree("a", 0.0, LIME, MODE_ALLEY), _tree("b", 5.0, LIME, MODE_ALLEY)]
    assert [issue.code for issue in _spacing(tight, PARAMS)] == ["spacing"]
    assert _spacing(fine, PARAMS) == []
    assert _spacing(alley, PARAMS) == []
