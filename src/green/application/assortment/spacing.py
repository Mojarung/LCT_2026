"""Шаг между деревьями по взрослым кронам: соседство мест в задаче подбора вида.

Сетка газона и аллея ставят места с шагом spacing_m (5 м) до подбора вида, а нужен шаг
зависит от вида: две ели с кроной 8 м в 5 м друг от друга - сплошная стена, два боярышника -
норма. Поэтому шаг пары деревьев вне ряда проверяется после выбора вида (params.tree_pair_step_m,
743-ПП, табл. 3.6.2: групповая посадка 5-7 м), и подбор решает его сам: на тесном месте -
вид с компактной кроной, а крупный вид - там, где рядом место свободно или его оставили
пустым. Ни одно место не становится допустимым по нормам благодаря этому - только выбор вида
и, в крайнем случае, пустое место с объяснением.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy.spatial import KDTree

from green.application.params import step_with_tolerance, tree_pair_min_m, tree_pair_step_m
from green.application.placement import in_alley
from green.application.wording import decimal_g
from green.domain.norms import PlantingType

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from green.application.params import PlanParams
    from green.domain.planting import Placement, Species

EPS_M = 1e-3  # тот же допуск, что у проверки плана (validation.EPS_M)
SOURCE = "743-ПП, табл. 3.6.2: групповая посадка деревьев 5-7 м"


@dataclass(frozen=True, slots=True)
class TreePair:
    first: str
    second: str
    distance: float
    row: bool  # оба места - ряд вдоль борта: шаг ряда, а не по кронам


@dataclass(frozen=True, slots=True)
class Neighbors:
    """Пары мест деревьев ближе наибольшего шага по кронам."""

    pairs: tuple[TreePair, ...]
    params: PlanParams

    def conflict(self, first: Species, second: Species, distance: float, *, row: bool) -> bool:
        return distance + EPS_M < tree_pair_min_m(first, second, self.params, row=row)

    def explain(self, species: Species, neighbour: Species, distance: float, *, row: bool) -> str:
        step = tree_pair_step_m(species, neighbour, self.params, row=row)
        return (
            f"до соседнего дерева ({neighbour.name_ru}) {decimal_g(round(distance, 2))} м, а шаг "
            f"по взрослым кронам {decimal_g(round(step, 2))} м ({SOURCE})"
        )


def tree_neighbors(placements: Sequence[Placement], params: PlanParams) -> Neighbors | None:
    """Соседство мест деревьев плана; None - шаг по кронам выключен или план не деревьев."""
    if not params.crown_spacing or params.planting_type is not PlantingType.TREE:
        return None
    trees = [p for p in placements if p.planting_type is PlantingType.TREE]
    if len(trees) < 2:  # noqa: PLR2004 - пара
        return Neighbors((), params)
    reach = step_with_tolerance(
        max(params.spacing_group_max_m, params.spacing_m), PlantingType.TREE
    )
    xy = np.array([(p.x, p.y) for p in trees], dtype=float)
    found = KDTree(xy).query_pairs(reach, output_type="ndarray")
    distances = np.hypot(*(xy[found[:, 0]] - xy[found[:, 1]]).T) if len(found) else []
    alley = [in_alley(p) for p in trees]
    pairs = tuple(
        TreePair(
            trees[i].placement_id,
            trees[j].placement_id,
            float(d),
            row=alley[i] and alley[j],
        )
        for (i, j), d in zip(found.tolist(), distances, strict=True)
    )
    return Neighbors(pairs, params)


@dataclass(frozen=True, slots=True)
class SpacingRows:
    """Что шаг по кронам добавляет в задачу: запрещённые пары (группа, вид) и строки
    «вид a в группе g и конфликтующий с ним вид в группе h - не вместе»."""

    banned: frozenset[tuple[str, str]]
    rows: tuple[tuple[tuple[str, str], tuple[tuple[str, str], ...]], ...]


def spacing_rows(
    neighbors: Neighbors,
    codes: Mapping[str, Sequence[str]],
    group_of: Mapping[str, str],
    fixed: Mapping[str, str],
    catalog: Mapping[str, Species],
) -> SpacingRows:
    """codes - виды-кандидаты группы, group_of - группа места, fixed - места с выбранным видом.

    Пара мест одной группы запрещает группе вид, которому тесно рядом с самим собой (группа
    сажается одним видом). Пара групп сводится к наименьшим расстояниям между ними - в ряду и
    вне ряда: этого достаточно, потому что шаг пары не растёт с расстоянием.
    """
    banned: set[tuple[str, str]] = set()
    closest: defaultdict[tuple[str, str], dict[bool, float]] = defaultdict(dict)
    for pair in neighbors.pairs:
        first, second = group_of.get(pair.first), group_of.get(pair.second)
        for group, other in ((first, pair.second), (second, pair.first)):
            if group is not None and other in fixed and other not in group_of:
                near = catalog[fixed[other]]
                banned.update(
                    (group, code)
                    for code in codes[group]
                    if neighbors.conflict(catalog[code], near, pair.distance, row=pair.row)
                )
        if first is None or second is None:
            continue
        if first == second:
            banned.update(
                (first, code)
                for code in codes[first]
                if neighbors.conflict(catalog[code], catalog[code], pair.distance, row=pair.row)
            )
            continue
        key = (first, second) if first < second else (second, first)
        best = closest[key]
        best[pair.row] = min(best.get(pair.row, np.inf), pair.distance)
    rows = []
    for (left, right), best in sorted(closest.items()):
        for code in codes[left]:
            if (left, code) in banned:
                continue
            clash = tuple(
                (right, other)
                for other in codes[right]
                if (right, other) not in banned
                and any(
                    neighbors.conflict(catalog[code], catalog[other], distance, row=row)
                    for row, distance in best.items()
                )
            )
            if clash:
                rows.append(((left, code), clash))
    return SpacingRows(frozenset(banned), tuple(rows))


def enforce_spacing(
    chosen: Mapping[str, str],
    neighbors: Neighbors,
    catalog: Mapping[str, Species],
    scores: Mapping[tuple[str, str], float],
) -> dict[str, str]:
    """Страховка после любого решателя: из тесной пары снимается место с меньшей оценкой.

    Решатель с конфликтами в строках их не допускает, но жадный запасной путь и решение,
    прерванное по времени, - могут; проверка плана такой план всё равно не пропустит.
    """
    kept = dict(chosen)
    for pair in sorted(neighbors.pairs, key=lambda p: (p.distance, p.first, p.second)):
        first, second = kept.get(pair.first), kept.get(pair.second)
        if first is None or second is None:
            continue
        if not neighbors.conflict(catalog[first], catalog[second], pair.distance, row=pair.row):
            continue
        lower = min(
            (pair.first, pair.second),
            key=lambda pid: (scores.get((pid, kept[pid]), 0.0), pid),
        )
        del kept[lower]
    return kept


def crowded(
    chosen: Mapping[str, str],
    options: Mapping[str, Sequence[str]],
    neighbors: Neighbors,
    catalog: Mapping[str, Species],
) -> dict[str, dict[str, str]]:
    """Какие виды места не встали из-за соседа: место -> вид -> объяснение с шагом и актом."""
    result: defaultdict[str, dict[str, str]] = defaultdict(dict)
    for pair in neighbors.pairs:
        for here, there in ((pair.first, pair.second), (pair.second, pair.first)):
            if there not in chosen or here not in options:
                continue
            near = catalog[chosen[there]]
            for code in options[here]:
                if code in result[here] or code == chosen.get(here):
                    continue
                species = catalog[code]
                if neighbors.conflict(species, near, pair.distance, row=pair.row):
                    result[here][code] = neighbors.explain(
                        species, near, pair.distance, row=pair.row
                    )
    return {pid: codes for pid, codes in result.items() if codes}
