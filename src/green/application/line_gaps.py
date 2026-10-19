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
_TOUCH_M = 1e-6
_MIN_POINTS = 2


def bridges(lines: Sequence[BaseGeometry], gap: float = GAP_M) -> list[BaseGeometry]:
    """Перемычки для разрывов не шире gap между линиями; сами линии не меняются."""
    parts = [
        p
        for g in lines
        for p in shapely.get_parts(g)
        if p.geom_type == "LineString" and len(p.coords) >= _MIN_POINTS and not p.is_ring
    ]
    if not parts:
        return []
    ends, outward = _ends(parts)
    tree = KDTree(ends)
    touching: set[int] = set()
    for a, b in tree.query_pairs(_TOUCH_M):
        if a // 2 != b // 2:
            touching.update((a, b))
    pairs = sorted(
        (float(np.linalg.norm(ends[a] - ends[b])), a, b)
        for a, b in tree.query_pairs(gap)
        if a // 2 != b // 2 and a not in touching and b not in touching
    )
    out: list[BaseGeometry] = []
    taken = set(touching)
    for distance, a, b in pairs:
        if a in taken or b in taken or distance <= _TOUCH_M:
            continue
        taken.update((a, b))
        out.append(shapely.LineString([ends[a], ends[b]]))
    out.extend(_extensions(parts, ends, outward, taken, gap))
    return out


def _ends(parts: Sequence[BaseGeometry]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Концы (2k - начало линии k, 2k + 1 - конец) и единичные направления наружу."""
    ends = []
    outward = []
    for p in parts:
        coords = np.asarray(p.coords, dtype=np.float64)[:, :2]
        ends.extend((coords[0], coords[-1]))
        outward.extend((_unit(coords[0] - coords[1]), _unit(coords[-1] - coords[-2])))
    return np.array(ends), np.array(outward)


def _extensions(
    parts: Sequence[BaseGeometry],
    ends: NDArray[np.float64],
    outward: NDArray[np.float64],
    taken: set[int],
    gap: float,
) -> list[BaseGeometry]:
    """Висячий конец продлевается вдоль своего направления до первой встречной линии."""
    free = [i for i in range(len(ends)) if i not in taken and outward[i].any()]
    if not free:
        return []
    rays = np.array(
        [shapely.LineString([ends[i], ends[i] + outward[i] * gap]) for i in free], dtype=object
    )
    index = shapely.STRtree(parts)
    ray_ids, part_ids = index.query(rays, predicate="intersects")
    best: dict[int, float] = {}
    for r, k in zip(ray_ids.tolist(), part_ids.tolist(), strict=True):
        i = free[r]
        if k == i // 2:
            continue
        hit = shapely.intersection(rays[r], parts[k])
        if hit.is_empty:
            continue
        origin = shapely.Point(ends[i])
        distance = float(shapely.distance(origin, hit))
        if _TOUCH_M < distance < best.get(i, np.inf):
            best[i] = distance
    return [
        shapely.LineString([ends[i], ends[i] + outward[i] * distance])
        for i, distance in best.items()
    ]


def _unit(v: NDArray[np.float64]) -> NDArray[np.float64]:
    n = float(np.linalg.norm(v))
    return v / n if n else v


__all__ = ["GAP_M", "bridges"]
