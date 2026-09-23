"""Analytic length of curb segments inside weighted circular crowns.

This is a geometry proxy, not a physical model of particulate removal. Each
covered interval takes the strongest crown weight, and removal loss uses the
second strongest. No metre-grid phase or polygonal circle approximation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely

if TYPE_CHECKING:
    from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class CurbCoverage:
    length_m: float
    covered_m: float
    weighted_m: float
    loss_m: NDArray[np.float64]
    reach_m: NDArray[np.float64]


def measure_crowns(
    segments: NDArray[np.float64],
    centers: NDArray[np.float64],
    radii: NDArray[np.float64],
    weights: NDArray[np.float64],
) -> CurbCoverage:
    """Integrate maximum weight and each crown's unique contribution along lines."""
    loss, reach = np.zeros(len(centers)), np.zeros(len(centers))
    lengths = np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1)
    total_length = float(lengths.sum())
    if not len(centers) or total_length <= 0:
        return CurbCoverage(total_length, 0.0, 0.0, loss, reach)
    boxes = shapely.box(
        centers[:, 0] - radii,
        centers[:, 1] - radii,
        centers[:, 0] + radii,
        centers[:, 1] + radii,
    )
    tree = shapely.STRtree(boxes)
    covered = weighted = 0.0
    for segment, length in zip(segments, lengths, strict=True):
        if length <= 0:
            continue
        ids = tree.query(shapely.LineString(segment))
        if not len(ids):
            continue
        unit = (segment[1] - segment[0]) / length
        relative = centers[ids] - segment[0]
        along = relative @ unit
        perpendicular = relative[:, 0] * unit[1] - relative[:, 1] * unit[0]
        half = np.sqrt(np.maximum(0.0, radii[ids] ** 2 - perpendicular**2))
        low, high = np.maximum(0.0, along - half), np.minimum(length, along + half)
        hit = high > low
        ids, low, high = ids[hit], low[hit], high[hit]
        reach[ids] += high - low
        intervals = list(zip(low.tolist(), high.tolist(), ids.tolist(), strict=True))
        amount, weighted_amount = _integrate(intervals, weights, loss)
        covered += amount
        weighted += weighted_amount
    return CurbCoverage(total_length, covered, float(weighted), loss, reach)


def _integrate(
    intervals: list[tuple[float, float, int]],
    weights: NDArray[np.float64],
    loss: NDArray[np.float64],
) -> tuple[float, float]:
    events = sorted(
        event
        for low, high, owner in intervals
        for event in ((low, owner, True), (high, owner, False))
    )
    active: set[int] = set()
    previous = covered = weighted = 0.0
    for position, owner, entering in events:
        span = position - previous
        if active and span > 0:
            ranked = sorted(active, key=lambda i: (-weights[i], i))
            best = ranked[0]
            second_weight = weights[ranked[1]] if len(ranked) > 1 else 0.0
            covered += span
            weighted += span * weights[best]
            loss[best] += span * (weights[best] - second_weight)
        if entering:
            active.add(owner)
        else:
            active.remove(owner)
        previous = position
    return covered, weighted
