"""Перемычки в разрывах линий-разделителей покрытий (борт, край покрытия, ограда, газон).

Съёмка замыкает газон и тротуар редко: линии борта обрываются у съездов, на стыках листов и у
знаков, край покрытия не доходит до борта на полметра. Карта покрытий для показа (3D-вид и
бумажная подоснова) делит землю на грани между этими линиями, и через каждый такой разрыв
материал соседней грани растекался пятном (Харьковская, 18-19.10.2026: «всё волнистое»).

Перемычки нужны только для показа: проверку посадок они не меняют. Два вида:

- концы двух разных линий ближе GAP_M - отрезок между ними;
- висячий конец, который смотрит на линию (Т-стык без касания), - продление вдоль его
  направления до первой линии, не дальше GAP_M.

Разрыв шире GAP_M (въезд, проход) остаётся открытым.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.spatial import KDTree

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

GAP_M = 2.0
NEIGHBOURS = 8  # ближайших концов на каждый конец
LOOP_MIN = 4  # своя линия замыкается, если она длиннее стольких разрывов
_TOUCH_M = 1e-6
_MIN_POINTS = 2
_LINE_TYPE_IDS = (1, 2)  # LineString, LinearRing


def bridges(lines: Sequence[BaseGeometry], gap: float = GAP_M) -> list[BaseGeometry]:
    """Перемычки для разрывов не шире gap между линиями; сами линии не меняются.

    Каждый конец смотрит только на NEIGHBOURS ближайших концов: на чертеже с тысячами коротких
    штрихов (разобранная штриховка, частый пунктир) все пары в радиусе gap - десятки миллионов,
    а перемычка всё равно идёт к ближайшему свободному концу."""
    drawn = shapely.get_parts(np.asarray(lines, dtype=object))
    drawn = drawn[
        np.isin(shapely.get_type_id(drawn), _LINE_TYPE_IDS)
        & (shapely.get_num_points(drawn) >= _MIN_POINTS)
    ]
    closed = shapely.is_ring(drawn)
    parts = list(drawn[~closed])
    # Замкнутый контур (стена здания) концов не имеет, но конец борта до него продлевается.
    rings = list(drawn[closed])
    if not parts:
        return []
    ends, outward = _ends(parts)
    tree = KDTree(ends)
    touching = np.zeros(len(ends), dtype=bool)
    for a, b in tree.query_pairs(_TOUCH_M):
        if a // 2 != b // 2:
            touching[[a, b]] = True
    out: list[BaseGeometry] = []
    taken = set(np.flatnonzero(touching).tolist())
    # Концы одной длинной линии тоже сводятся: контур газона, не дотянутый до начала на
    # полметра, - почти замкнутое кольцо. Короткий крючок (длина до LOOP_MIN разрывов) - нет.
    loops = shapely.length(np.array(parts, dtype=object)) > LOOP_MIN * gap
    for a, b in _nearest_pairs(tree, ends, touching, gap, loops):
        if a in taken or b in taken:
            continue
        taken.update((a, b))
        out.append(shapely.LineString([ends[a], ends[b]]))
    out.extend(_extensions([*parts, *rings], ends, outward, taken, gap))
    return out


def _nearest_pairs(
    tree: KDTree,
    ends: NDArray[np.float64],
    touching: NDArray[np.bool_],
    gap: float,
    loops: NDArray[np.bool_],
) -> list[tuple[int, int]]:
    """Пары концов разных линий ближе gap, от ближней к дальней, по NEIGHBOURS соседей."""
    n = len(ends)
    k = min(NEIGHBOURS + 1, n)
    distance, index = tree.query(ends, k=k, distance_upper_bound=gap)
    distance = np.asarray(distance).reshape(n, k)
    index = np.asarray(index).reshape(n, k)
    rows = np.repeat(np.arange(n), k)
    cols = index.ravel()
    lengths = distance.ravel()
    keep = (cols < n) & (lengths > _TOUCH_M)
    rows, cols, lengths = rows[keep], cols[keep], lengths[keep]
    keep = ((rows // 2 != cols // 2) | loops[rows // 2]) & ~touching[rows] & ~touching[cols]
    first = np.minimum(rows[keep], cols[keep])
    second = np.maximum(rows[keep], cols[keep])
    lengths = lengths[keep]
    order = np.lexsort((second, first, lengths))
    seen: set[tuple[int, int]] = set()
    pairs = []
    for a, b in zip(first[order].tolist(), second[order].tolist(), strict=True):
        if (a, b) not in seen:
            seen.add((a, b))
            pairs.append((a, b))
    return pairs


def _ends(parts: Sequence[BaseGeometry]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Концы (2k - начало линии k, 2k + 1 - конец) и единичные направления наружу."""
    xy, owner = shapely.get_coordinates(np.asarray(parts, dtype=object), return_index=True)
    first = np.flatnonzero(np.r_[True, owner[1:] != owner[:-1]])
    last = np.r_[first[1:], len(owner)] - 1
    ends = np.empty((2 * len(first), 2))
    ends[0::2], ends[1::2] = xy[first], xy[last]
    outward = np.empty_like(ends)
    outward[0::2] = xy[first] - xy[first + 1]
    outward[1::2] = xy[last] - xy[last - 1]
    norm = np.linalg.norm(outward, axis=1, keepdims=True)
    return ends, np.divide(outward, norm, out=np.zeros_like(outward), where=norm > 0)


def _extensions(
    parts: Sequence[BaseGeometry],
    ends: NDArray[np.float64],
    outward: NDArray[np.float64],
    taken: set[int],
    gap: float,
) -> list[BaseGeometry]:
    """Висячий конец продлевается вдоль своего направления до первой встречной линии.

    parts - сначала линии с концами (их номера - номера концов // 2), за ними замкнутые."""
    free = [i for i in range(len(ends)) if i not in taken and outward[i].any()]
    if not free:
        return []
    rays = np.array(
        [shapely.LineString([ends[i], ends[i] + outward[i] * gap]) for i in free], dtype=object
    )
    lines = np.array(parts, dtype=object)
    ray_ids, part_ids = shapely.STRtree(lines).query(rays, predicate="intersects")
    own = np.array([free[r] // 2 for r in ray_ids.tolist()], dtype=np.int64)
    other = part_ids != own
    ray_ids, part_ids = ray_ids[other], part_ids[other]
    if not len(ray_ids):
        return []
    hits = shapely.intersection(rays[ray_ids], lines[part_ids])
    origins = shapely.points(ends[[free[r] for r in ray_ids.tolist()]])
    distances = shapely.distance(origins, hits)
    best: dict[int, float] = {}
    for r, distance in zip(ray_ids.tolist(), distances.tolist(), strict=True):
        i = free[r]
        if _TOUCH_M < distance < best.get(i, np.inf):
            best[i] = distance
    return [
        shapely.LineString([ends[i], ends[i] + outward[i] * distance])
        for i, distance in best.items()
    ]


__all__ = ["GAP_M", "bridges"]
