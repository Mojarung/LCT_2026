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


@dataclass(frozen=True, slots=True)
class FixedCrowns:
    """Crowns that are the same in every evaluation (existing trees), measured once.

    Per segment the covered and weighted length of these crowns alone; an evaluation only
    re-integrates the segments its own crowns touch.
    """

    centers: NDArray[np.float64]
    radii: NDArray[np.float64]
    weights: NDArray[np.float64]
    covered: NDArray[np.float64]
    weighted: NDArray[np.float64]
    tree: shapely.STRtree | None

    @property
    def covered_m(self) -> float:
        return float(self.covered.sum())


def fixed_crowns(
    segments: NDArray[np.float64],
    centers: NDArray[np.float64],
    radii: NDArray[np.float64],
    weights: NDArray[np.float64],
) -> FixedCrowns:
    covered, weighted = np.zeros(len(segments)), np.zeros(len(segments))
    tree = shapely.STRtree(_boxes(centers, radii)) if len(centers) else None
    lengths = np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1)
    loss = np.zeros(len(centers))
    for k, (segment, length) in enumerate(zip(segments, lengths, strict=True)):
        if length <= 0 or tree is None:
            continue
        ids = tree.query(shapely.LineString(segment))
        intervals = _intervals(segment, length, ids, centers, radii)
        if intervals:
            covered[k], weighted[k] = _integrate(intervals, weights, loss)
    return FixedCrowns(centers, radii, weights, covered, weighted, tree)


def _boxes(centers: NDArray[np.float64], radii: NDArray[np.float64]) -> NDArray[np.object_]:
    return shapely.box(
        centers[:, 0] - radii,
        centers[:, 1] - radii,
        centers[:, 0] + radii,
        centers[:, 1] + radii,
    )


def _intervals(  # noqa: PLR0913, PLR0917 - отрезок, круги и сдвиг номеров владельцев
    segment: NDArray[np.float64],
    length: float,
    ids: NDArray[np.intp],
    centers: NDArray[np.float64],
    radii: NDArray[np.float64],
    offset: int = 0,
) -> list[tuple[float, float, int]]:
    """Pieces of the segment under each crown: (from, to, owner + offset)."""
    if not len(ids):
        return []
    unit = (segment[1] - segment[0]) / length
    relative = centers[ids] - segment[0]
    along = relative @ unit
    perpendicular = relative[:, 0] * unit[1] - relative[:, 1] * unit[0]
    half = np.sqrt(np.maximum(0.0, radii[ids] ** 2 - perpendicular**2))
    low, high = np.maximum(0.0, along - half), np.minimum(length, along + half)
    hit = high > low
    return list(
        zip(low[hit].tolist(), high[hit].tolist(), (ids[hit] + offset).tolist(), strict=True)
    )


def measure_crowns(
    segments: NDArray[np.float64],
    centers: NDArray[np.float64],
    radii: NDArray[np.float64],
    weights: NDArray[np.float64],
    *,
    fixed: FixedCrowns | None = None,
) -> CurbCoverage:
    """Integrate maximum weight and each crown's unique contribution along lines."""
    if fixed is not None:
        return _with_fixed(segments, centers, radii, weights, fixed)
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


def _with_fixed(
    segments: NDArray[np.float64],
    centers: NDArray[np.float64],
    radii: NDArray[np.float64],
    weights: NDArray[np.float64],
    fixed: FixedCrowns,
) -> CurbCoverage:
    """Fixed crowns' totals plus the segments this evaluation's crowns touch, re-integrated
    together with the fixed crowns there: the same sums as one pass over all crowns."""
    count = len(centers)
    lengths = np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1)
    total_length = float(lengths.sum())
    covered, weighted = float(fixed.covered.sum()), float(fixed.weighted.sum())
    all_weights = np.concatenate([weights, fixed.weights])
    loss = np.zeros(count + len(fixed.centers))
    reach = np.zeros(count)
    if not count or total_length <= 0:
        return CurbCoverage(total_length, float(covered), float(weighted), loss[:count], reach)
    lines = shapely.linestrings(segments)
    seg_ids, crown_ids = shapely.STRtree(_boxes(centers, radii)).query(lines)
    touched: dict[int, list[int]] = {}
    for s, c in zip(seg_ids.tolist(), crown_ids.tolist(), strict=True):
        touched.setdefault(s, []).append(c)
    for k, ids in touched.items():
        length = float(lengths[k])
        if length <= 0:
            continue
        own = _intervals(segments[k], length, np.array(ids), centers, radii)
        if not own:
            continue
        for low, high, owner in own:
            reach[owner] += high - low
        others = fixed.tree.query(lines[k]) if fixed.tree is not None else np.zeros(0, int)
        base = _intervals(segments[k], length, others, fixed.centers, fixed.radii, count)
        amount, weighted_amount = _integrate([*own, *base], all_weights, loss)
        covered += amount - float(fixed.covered[k])
        weighted += weighted_amount - float(fixed.weighted[k])
    return CurbCoverage(total_length, float(covered), float(weighted), loss[:count], reach)


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
