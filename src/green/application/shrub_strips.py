"""Recognise Moscow 1:500 sign 273: dotted line interrupted by oOo triplets.

The layer may incorrectly say «Полоса деревьев». Require the geometry of at least
 two complete motifs, never just a dense row. Dimensions are graphic, not crowns.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import minimum_spanning_tree
from shapely import STRtree
from shapely.geometry import LineString, Point

from green.domain.objects import ClassificationEvidence, ObjectClass

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature

SHRUB_STRIP_SOURCE = "SHRUB_STRIP"
SHRUB_STRIP_METHOD = "topographic_shrub_strip:273"
MIN_MARKS = 9  # two triplets and at least three intervening dots
MIN_MOTIFS = 2
MIN_GAP_DOTS = 3
RADIUS_TOLERANCE_M = 1e-5
MIN_TURN_COSINE = -0.05  # allow a right-angle corner, reject a reversal
DOT_RATIO_MAX = 0.25
SMALL_RATIO_MIN, SMALL_RATIO_MAX = 0.62, 0.78  # nominal 0.7
LARGE_RATIO_MIN = 0.92
PATH_DEGREE = 2

type XY = tuple[float, float]
type Edge = tuple[int, int, float]


def recognise_shrub_strips(features: Sequence[Feature]) -> tuple[Feature, ...]:
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, f in enumerate(features):
        method = f.classification.method if f.classification else ""
        if (
            f.object_class in {ObjectClass.EXISTING_TREE, ObjectClass.EXISTING_SHRUB}
            and f.symbol is None
            and f.circle_radius_m is not None
            and 0 < f.circle_radius_m <= 1
            and not method.startswith("explicit_")
        ):
            groups[(f.ref.file_sha8, f.ref.xref_hash8, f.layer)].append(i)
    result = list(features)
    strips = []
    consumed = []
    for indices in groups.values():
        for ids, coords in _matches(features, indices):
            first = features[ids[0]]
            ref = replace(first.ref, handle=f"{first.ref.handle}+shrub-strip")
            evidence = ClassificationEvidence(f"shrub_strip_member:{ref}")
            for i in ids:
                result[i] = replace(
                    features[i], object_class=ObjectClass.IGNORE, classification=evidence
                )
                consumed.append((features[i], evidence))
            strips.append(
                replace(
                    first,
                    ref=ref,
                    geometry=LineString(coords),
                    object_class=ObjectClass.EXISTING_SHRUB,
                    source_entity_type=SHRUB_STRIP_SOURCE,
                    circle_radius_m=None,
                    circle_center_m=None,
                    classification=ClassificationEvidence(SHRUB_STRIP_METHOD),
                )
            )
    return (*_without_ink(result, consumed), *strips)


def _circle_point(feature: Feature) -> Point:
    return (
        Point(feature.circle_center_m)
        if feature.circle_center_m is not None
        else feature.geometry.centroid
    )


def _matches(
    features: Sequence[Feature], indices: list[int]
) -> Iterator[tuple[list[int], list[XY]]]:
    # Duplicate survey sheets can repeat a mark. Preserve their provenance but
    # match unique centres; disagreeing radii at the same centre are ambiguous.
    at: dict[tuple[float, float], list[int]] = defaultdict(list)
    for i in indices:
        p = _circle_point(features[i])
        at[(round(p.x, 6), round(p.y, 6))].append(i)
    centres = list(at)
    if len(centres) < MIN_MARKS:
        return
    radii = [float(features[at[p][0]].circle_radius_m or 0) for p in centres]
    if any(
        max(float(features[i].circle_radius_m or 0) for i in ids)
        - min(float(features[i].circle_radius_m or 0) for i in ids)
        > RADIUS_TOLERANCE_M
        for ids in at.values()
    ):
        return
    points = [_circle_point(features[at[p][0]]) for p in centres]
    for members, edges in _components(points, radii):
        order = _path(members, edges)
        if not order or not _motifs([radii[i] for i in order]):
            continue
        coords = [centres[i] for i in order]
        # A hedge may turn a street corner. Reject a reversal; branching
        # and crossings have already failed the simple-path check.
        v = np.diff(np.asarray(coords), axis=0)
        cosines = np.sum(v[:-1] * v[1:], axis=1) / (
            np.linalg.norm(v[:-1], axis=1) * np.linalg.norm(v[1:], axis=1)
        )
        if np.any(cosines < MIN_TURN_COSINE):
            continue
        yield [i for j in members for i in at[centres[j]]], coords


def _components(
    points: list[BaseGeometry], radii: list[float]
) -> list[tuple[list[int], list[Edge]]]:
    near = STRtree(points).query(points, predicate="dwithin", distance=6 * max(radii))
    parent = list(range(len(points)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    edges = []
    for left, right in zip(*near, strict=True):
        a, b = int(left), int(right)
        if a >= b:
            continue
        distance = points[a].distance(points[b])
        # A local limit prevents one unrelated large circle joining distant rows.
        if distance > 6 * max(radii[a], radii[b], 0.25):
            continue
        edges.append((a, b, distance))
        ra, rb = root(a), root(b)
        if ra != rb:
            parent[rb] = ra
    components: dict[int, list[int]] = defaultdict(list)
    for i in range(len(points)):
        components[root(i)].append(i)
    by_component: dict[int, list[tuple[int, int, float]]] = defaultdict(list)
    for a, b, d in edges:
        by_component[root(a)].append((a, b, d))
    return [(members, by_component[key]) for key, members in components.items()]


def _without_ink(
    result: list[Feature], consumed: list[tuple[Feature, ClassificationEvidence]]
) -> list[Feature]:
    # Short hatch strokes inside the dots are symbol ink, not lawn boundaries.
    if consumed:
        disks = [
            _circle_point(f).buffer(float(f.circle_radius_m or 0) + RADIUS_TOLERANCE_M)
            for f, _ in consumed
        ]
        index = STRtree(disks)
        for i, f in enumerate(result):
            method = f.classification.method if f.classification else ""
            if (
                f.symbol is not None
                or method.startswith("explicit_")
                or f.geometry.geom_type != "LineString"
            ):
                continue
            for j in index.query(f.geometry, predicate="within"):
                original, evidence = consumed[int(j)]
                if (f.layer, f.ref.file_sha8, f.ref.xref_hash8) == (
                    original.layer,
                    original.ref.file_sha8,
                    original.ref.xref_hash8,
                ):
                    result[i] = replace(f, object_class=ObjectClass.IGNORE, classification=evidence)
                    break
    return result


def _path(members: list[int], edges: list[tuple[int, int, float]]) -> list[int] | None:
    if len(members) < MIN_MARKS:
        return None
    local = {v: i for i, v in enumerate(members)}
    graph = coo_matrix(
        (
            [d for _, _, d in edges],
            ([local[a] for a, _, _ in edges], [local[b] for _, b, _ in edges]),
        ),
        shape=(len(members), len(members)),
    ).tocsr()
    tree = minimum_spanning_tree(graph).tocoo()
    adjacent: dict[int, list[int]] = defaultdict(list)
    for a, b in zip(tree.row, tree.col, strict=True):
        adjacent[int(a)].append(int(b))
        adjacent[int(b)].append(int(a))
    ends = [i for i in range(len(members)) if len(adjacent[i]) == 1]
    if len(ends) != PATH_DEGREE or any(len(v) > PATH_DEGREE for v in adjacent.values()):
        return None
    order = [ends[0]]
    previous = -1
    while len(order) < len(members):
        next_points = [i for i in adjacent[order[-1]] if i != previous]
        if len(next_points) != 1:
            return None
        previous = order[-1]
        order.append(next_points[0])
    return [members[i] for i in order]


def _motifs(radii: list[float]) -> bool:
    large = max(radii)
    tokens = []
    for radius in radii:
        ratio = radius / large
        if ratio <= DOT_RATIO_MAX:
            tokens.append(".")
        elif SMALL_RATIO_MIN <= ratio <= SMALL_RATIO_MAX:
            tokens.append("o")
        elif ratio >= LARGE_RATIO_MIN:
            tokens.append("O")
        else:
            return False
    text = "".join(tokens)
    gaps = re.findall(r"(?<=[oO])\.+(?=[oO])", text)
    if not gaps or any(len(gap) < MIN_GAP_DOTS for gap in gaps):
        return False
    runs = [run for run in text.split(".") if run]
    complete = sum(run == "oOo" for run in runs)
    # Partial end motifs are permitted at a clipped survey boundary only.
    for i, run in enumerate(runs):
        if run == "oOo":
            continue
        if i == 0 and text.startswith(run) and run in {"o", "Oo"}:
            continue
        if i == len(runs) - 1 and text.endswith(run) and run in {"o", "oO"}:
            continue
        return False
    return complete >= MIN_MOTIFS and "..." in text
