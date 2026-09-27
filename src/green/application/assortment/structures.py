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

    from numpy.typing import NDArray

    from green.domain.planting import Placement

ROW = "row"
GROUP = "group"
SINGLE = "single"
_LINK_FACTOR = 1.5  # во сколько шагов посадки укладывается разрыв внутри одной структуры
_MIN_ROW = 2  # два дерева вдоль борта - уже ряд
_MIN_GROUP = 3  # две точки на газоне - ещё не группа
_LABEL_MODES = {label: mode for mode, label in MODE_LABELS.items()}
_FRAME_DECIMALS = 6  # micrometre ordering tolerance; physical coordinates are untouched
_COINCIDENT_M2 = 1e-12
_ISOTROPY_REL = 1e-8


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
    local = _principal_coordinates(np.array([points[i] for i in ids], dtype=float))
    ordered = [ids[i] for i in sorted(range(len(ids)), key=lambda i: (*local[i], ids[i]))]
    half = len(ordered) // 2
    left = tuple(sorted(ordered[:half]))
    right = tuple(sorted(ordered[half:]))
    return _patches(left, points, patch_size) + _patches(right, points, patch_size)


def _principal_coordinates(xy: NDArray[np.float64]) -> NDArray[np.float64]:
    """Order patches in their own axes; no geometry or feasibility is rounded.

    Axis signs are arbitrary in an eigensolver. Anchor each sign to the farthest
    projected member, breaking geometric ties by the stable input id order.
    Isotropic groups have no principal direction: use an actual radial member
    instead of the eigensolver's world-axis choice. Fully coincident points keep
    id order. These symmetry choices require the same member identities.
    """
    relative = xy - xy[0]
    centered = relative - relative.mean(axis=0)
    values, vectors = np.linalg.eigh(centered.T @ centered)
    if values[-1] <= _COINCIDENT_M2:
        return np.zeros_like(centered)
    if values[-1] - values[0] <= _ISOTROPY_REL * values[-1]:
        lengths = np.linalg.norm(centered, axis=1)
        anchor = int(np.argmax(np.round(lengths, _FRAME_DECIMALS)))
        direction = centered[anchor] / lengths[anchor]
    else:
        direction = vectors[:, -1]
    frame = np.column_stack((direction, (-direction[1], direction[0])))
    # Ignore sub-micrometre projection noise only in ordering, never in checks.
    local = np.round(centered @ frame, _FRAME_DECIMALS)
    for axis in range(2):
        anchor = int(np.argmax(np.abs(local[:, axis])))
        if local[anchor, axis] < 0:
            local[:, axis] *= -1
    return local


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
