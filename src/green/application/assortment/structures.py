"""Ряды, группы и одиночки: посадка получает вид не сама по себе, а вместе с соседями.

Ряд вдоль борта с чередующимися видами выглядит случайным, поэтому вид назначается
структуре целиком (ряд - строго один вид, группа - доминант и спутники). Структуры
строятся одиночной связью: соседи ближе полутора шагов посадки в пределах одного приёма
размещения. Приёмы не смешиваются: аллея и заполнение газона - разные структуры, даже
если точки рядом.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import KDTree

from green.application.placement import (
    MODE_ALLEY,
    MODE_CURB_HEDGE,
    MODE_LABELS,
    MODE_LAWN,
    MODE_SHRUB_FILL,
    MODE_SHRUB_GROUP,
    MODE_SHRUB_ROW,
    MODE_UNDERSTORY,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from green.domain.planting import Placement

ROW = "row"
GROUP = "group"
SINGLE = "single"
_LINK_FACTOR = 1.5  # во сколько шагов посадки укладывается разрыв внутри одной структуры
_MIN_ROW = 2  # два дерева вдоль борта - уже ряд
_MIN_GROUP = 3  # две точки на газоне - ещё не группа
_LABEL_MODES = {label: mode for mode, label in MODE_LABELS.items()}


@dataclass(frozen=True, slots=True)
class Structure:
    structure_id: str  # row-1, group-2, single-3
    kind: str  # row | group | single
    placement_ids: tuple[str, ...]


def build_structures(
    placements: Sequence[Placement], spacing_m: float, patch_size: int = 10
) -> tuple[Structure, ...]:
    """Разбить посадки на структуры, каждая из которых получит один вид.

    Кластер длиннее patch_size делится на участки: аллея в сто деревьев одной породы
    возможна, но участок в десять даёт кварталы разного вида, как и делают проектировщики,
    а заодно держит задачу назначения маленькой.
    """
    radius = max(spacing_m, 0.1) * _LINK_FACTOR
    points = {p.placement_id: (p.x, p.y) for p in placements}
    clusters: list[tuple[str, tuple[str, ...]]] = []
    for mode in sorted({_mode_of(p) for p in placements}):
        members = sorted(
            (p for p in placements if _mode_of(p) == mode), key=lambda p: p.placement_id
        )
        for ids in _clusters(members, radius):
            kind = _kind(mode, len(ids))
            if kind == SINGLE:
                # Одиночка - ровно одна посадка: две точки на газоне не образуют композицию,
                # и связывать их одним видом не за что.
                clusters += [(SINGLE, (placement_id,)) for placement_id in ids]
            else:
                clusters += [(kind, patch) for patch in _patches(ids, points, patch_size)]
    clusters.sort(key=lambda item: item[1][0])
    return tuple(
        Structure(structure_id=f"{kind}-{number}", kind=kind, placement_ids=ids)
        for number, (kind, ids) in enumerate(clusters, start=1)
    )


def _patches(
    ids: tuple[str, ...], points: Mapping[str, tuple[float, float]], patch_size: int
) -> list[tuple[str, ...]]:
    """Деление кластера пополам по длинной оси, пока участок не влезет в patch_size."""
    if len(ids) <= max(patch_size, _MIN_ROW):
        return [ids]
    xs = [points[i][0] for i in ids]
    ys = [points[i][1] for i in ids]
    axis = 0 if (max(xs) - min(xs)) >= (max(ys) - min(ys)) else 1
    ordered = sorted(ids, key=lambda i: (points[i][axis], points[i][1 - axis], i))
    half = len(ordered) // 2
    left = tuple(sorted(ordered[:half]))
    right = tuple(sorted(ordered[half:]))
    return _patches(left, points, patch_size) + _patches(right, points, patch_size)


def _mode_of(placement: Placement) -> str:
    for note in placement.notes:
        if note in _LABEL_MODES:
            return _LABEL_MODES[note]
    return "other"


def _kind(mode: str, size: int) -> str:
    if size < _MIN_ROW:
        return SINGLE
    if mode in {MODE_SHRUB_GROUP, MODE_UNDERSTORY, MODE_SHRUB_FILL}:
        return GROUP
    if mode in {MODE_ALLEY, MODE_SHRUB_ROW, MODE_CURB_HEDGE}:
        return ROW
    if mode == MODE_LAWN and size >= _MIN_GROUP:
        return GROUP
    return SINGLE if mode == MODE_LAWN else ROW


def _clusters(members: Sequence[Placement], radius: float) -> list[tuple[str, ...]]:
    """Одиночная связь: компоненты связности графа «соседи ближе radius»."""
    if not members:
        return []
    if len(members) == 1:
        return [(members[0].placement_id,)]
    points = np.array([(p.x, p.y) for p in members], dtype=float)
    pairs = KDTree(points).query_pairs(radius, output_type="ndarray")
    size = len(members)
    if len(pairs):
        graph = coo_matrix(
            (np.ones(len(pairs), dtype=np.int8), (pairs[:, 0], pairs[:, 1])), shape=(size, size)
        )
        _, labels = connected_components(graph, directed=False)
    else:
        labels = np.arange(size)
    buckets: dict[int, list[str]] = {}
    for index, label in enumerate(labels):
        buckets.setdefault(int(label), []).append(members[index].placement_id)
    return [tuple(sorted(ids)) for ids in buckets.values()]
