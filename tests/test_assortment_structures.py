"""Структуры посадок: ряды вдоль борта, группы на газоне, одиночки."""

from __future__ import annotations

from green.application.assortment.structures import build_structures
from green.application.placement import MODE_LABELS
from green.domain.norms import PlantingType
from green.domain.planting import Placement, Species, Verdict

ALLEY = MODE_LABELS["alley"]
LAWN = MODE_LABELS["lawn"]
SPACING = 6.0


def _placement(number: int, x: float, y: float, note: str) -> Placement:
    return Placement(
        placement_id=f"p-{number:03d}",
        number=number,
        planting_type=PlantingType.TREE,
        species=Species("tilia_cordata", "Липа", "Tilia cordata", 4.0),
        x=x,
        y=y,
        verdict=Verdict.ALLOWED,
        checks=(),
        notes=(note,),
    )


def _row(count: int, start: float, number_from: int, note: str = ALLEY) -> list[Placement]:
    return [_placement(number_from + i, start + i * SPACING, 0.0, note) for i in range(count)]


def test_alley_points_in_one_line_make_a_single_row() -> None:
    structures = build_structures(_row(8, 0.0, 1), SPACING)
    assert len(structures) == 1
    assert structures[0].kind == "row"
    assert len(structures[0].placement_ids) == 8


def test_gap_longer_than_one_and_a_half_steps_splits_the_row() -> None:
    first = _row(4, 0.0, 1)
    second = _row(4, 3 * SPACING + 20.0, 5)
    structures = build_structures([*first, *second], SPACING)
    assert [s.kind for s in structures] == ["row", "row"]
    assert [len(s.placement_ids) for s in structures] == [4, 4]


def test_lawn_clusters_become_groups_and_a_lone_point_stays_single() -> None:
    left = [_placement(1 + i, i % 2 * 3.0, i // 2 * 3.0, LAWN) for i in range(4)]
    right = [_placement(5 + i, 40.0 + i % 2 * 3.0, i // 2 * 3.0, LAWN) for i in range(4)]
    lonely = [_placement(9, 200.0, 200.0, LAWN)]
    structures = build_structures([*left, *right, *lonely], SPACING)
    kinds = sorted(s.kind for s in structures)
    assert kinds == ["group", "group", "single"]
    single = next(s for s in structures if s.kind == "single")
    assert single.placement_ids == ("p-009",)


def test_two_lawn_points_are_not_a_group() -> None:
    structures = build_structures(
        [_placement(1, 0.0, 0.0, LAWN), _placement(2, 2.0, 0.0, LAWN)], SPACING
    )
    assert [s.kind for s in structures] == ["single", "single"]


def test_modes_do_not_merge_even_when_points_are_close() -> None:
    structures = build_structures(
        [_placement(1, 0.0, 0.0, ALLEY), _placement(2, 1.0, 0.0, LAWN)], SPACING
    )
    assert len(structures) == 2


def test_every_placement_lands_in_exactly_one_structure_and_ids_are_stable() -> None:
    placements = [*_row(6, 0.0, 1), *[_placement(10 + i, 50.0 + i, 30.0, LAWN) for i in range(5)]]
    first = build_structures(placements, SPACING)
    second = build_structures(list(reversed(placements)), SPACING)
    assert first == second
    assert all(len(s.placement_ids) == 1 for s in first if s.kind == "single")
    assigned = [pid for s in first for pid in s.placement_ids]
    assert sorted(assigned) == sorted(p.placement_id for p in placements)
    assert len(assigned) == len(set(assigned))
    assert len({s.structure_id for s in first}) == len(first)


def test_no_placements_give_no_structures() -> None:
    assert build_structures([], SPACING) == ()
