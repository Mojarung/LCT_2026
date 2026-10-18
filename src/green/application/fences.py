"""Ограда из штрихов - сплошной линией (Харьковская, 18.10.2026).

Съёмка рисует ограду штрихами: на Харьковской 4 362 куска, 96 % короче 3 м, у четверти
зазор 0,5 м до соседнего. Зазор равен клетке карты покрытий, и материал от подписи («А»)
протекал сквозь ограду на газон, а в 3D-виде ограда стояла с дырами. Здесь зазоры между
штрихами закрываются перемычками - отдельными объектами того же класса и слоя: сами
штрихи не меняются, исходные ссылки на них в объяснениях остаются.

Перемычка ставится, если конец одного штриха смотрит на конец другого: зазор не больше
GAP_M и оба штриха продолжают друг друга с поворотом не круче TURN_DEG. Угол ограды
(поворот круче) закрывается, только если зазор не больше CORNER_GAP_M. Проём шире GAP_M -
калитка или проход - остаётся открытым.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.spatial import KDTree

from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from green.domain.objects import Feature

GAP_M = 1.0
CORNER_GAP_M = 0.6
TURN_DEG = 30.0
_MIN_POINTS = 2


def bridge_fence_gaps(features: Sequence[Feature]) -> tuple[tuple[Feature, ...], int]:
    """Объекты чертежа и перемычки между штрихами ограды; второе значение - число перемычек."""
    strokes = [
        f
        for f in features
        if f.object_class is ObjectClass.FENCE
        and f.geometry.geom_type == "LineString"
        and len(f.geometry.coords) >= _MIN_POINTS
        and not f.geometry.is_ring
    ]
    if len(strokes) < _MIN_POINTS:
        return tuple(features), 0
    ends, outward = _ends(strokes)
    tree = KDTree(ends)
    limit = math.cos(math.radians(TURN_DEG))
    candidates = []
    for a, b in tree.query_pairs(GAP_M):
        if a // 2 == b // 2:
            continue
        gap = float(np.linalg.norm(ends[a] - ends[b]))
        if gap == 0:
            continue
        straight = _continues(ends[a], outward[a], ends[b], outward[b], limit)
        if straight or gap <= CORNER_GAP_M:
            # Прямое продолжение важнее угла: при равном зазоре берётся первым.
            candidates.append((0 if straight else 1, gap, a, b))
    taken: set[int] = set()
    touching = _touching(tree)
    bridges = []
    for _, _, a, b in sorted(candidates):
        if a in taken or b in taken or a in touching or b in touching:
            continue
        taken.update((a, b))
        source = strokes[a // 2]
        bridges.append(
            replace(
                source,
                geometry=shapely.LineString([ends[a], ends[b]]),
                classification=source.classification,
            )
        )
    return (*features, *bridges), len(bridges)


def _ends(strokes: Sequence[Feature]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Концы штрихов (2k - начало штриха k, 2k + 1 - конец) и направления наружу."""
    ends = []
    outward = []
    for f in strokes:
        coords = np.asarray(f.geometry.coords, dtype=np.float64)[:, :2]
        ends.extend((coords[0], coords[-1]))
        outward.extend((_unit(coords[0] - coords[1]), _unit(coords[-1] - coords[-2])))
    return np.array(ends), np.array(outward)


def _touching(tree: KDTree) -> set[int]:
    """Концы, которые уже стыкуются с другим штрихом: им перемычка не нужна."""
    joined: set[int] = set()
    for a, b in tree.query_pairs(1e-6):
        if a // 2 != b // 2:
            joined.update((a, b))
    return joined


def _unit(v: NDArray[np.float64]) -> NDArray[np.float64]:
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _continues(
    pa: NDArray[np.float64],
    da: NDArray[np.float64],
    pb: NDArray[np.float64],
    db: NDArray[np.float64],
    limit: float,
) -> bool:
    toward = _unit(pb - pa)
    return bool(da @ toward >= limit and db @ -toward >= limit and da @ -db >= limit)


__all__ = ["CORNER_GAP_M", "GAP_M", "bridge_fence_gaps"]
