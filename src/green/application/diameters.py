"""Привязка подписей диаметров (например, `d=400ж.б.`) к линиям сетей того же слоя."""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING

from shapely import STRtree
from shapely.geometry import Point

if TYPE_CHECKING:
    from green.domain.objects import Feature, ObjectClass, TextLabel

_DIAMETER = re.compile(r"(?:^|[^a-zа-я])(?:d|ду|ø|ф)\s*=?\s*(\d{2,4})", re.IGNORECASE)
_MIN_MM = 20
_MAX_MM = 4000
_CHAIN_DEGREE = 2
_OPEN_CHAIN_ENDS = 2


def parse_diameter_m(text: str) -> float | None:
    match = _DIAMETER.search(text.replace(" ", ""))
    if match is None:
        return None
    millimetres = int(match.group(1))
    if not _MIN_MM <= millimetres <= _MAX_MM:
        return None
    return millimetres / 1000


def assign_diameters(
    features: tuple[Feature, ...], labels: tuple[TextLabel, ...], radius_m: float
) -> tuple[Feature, ...]:
    """Каждой сети достаётся наибольший диаметр из подписей её слоя в радиусе radius_m."""
    utility_by_layer: dict[str, list[int]] = defaultdict(list)
    for index, feature in enumerate(features):
        if feature.object_class.is_utility:
            utility_by_layer[feature.layer].append(index)

    labels_by_layer: dict[str, list[tuple[Point, float]]] = defaultdict(list)
    for label in labels:
        diameter = parse_diameter_m(label.text)
        if diameter is not None and label.layer in utility_by_layer:
            labels_by_layer[label.layer].append((Point(label.x, label.y), diameter))

    best: dict[int, float] = {}
    for layer, items in labels_by_layer.items():
        indices = utility_by_layer[layer]
        tree = STRtree([features[i].geometry for i in indices])
        points = [point for point, _ in items]
        pairs = tree.query_nearest(points, max_distance=radius_m, all_matches=False)
        for label_pos, tree_pos in zip(pairs[0], pairs[1], strict=True):
            feature_index = indices[int(tree_pos)]
            diameter = items[int(label_pos)][1]
            best[feature_index] = max(best.get(feature_index, 0.0), diameter)

    assigned = tuple(
        replace(f, diameter_m=best[i]) if i in best else f for i, f in enumerate(features)
    )
    return _propagate_chain_diameters(assigned)


def _propagate_chain_diameters(features: tuple[Feature, ...]) -> tuple[Feature, ...]:
    """Restore an assigned diameter across an exact, unambiguous open chain.

    Preserve existing assignments. Branches, interior intersections, overlaps,
    uncertain geometry and conflicting diameters retain the previous behavior.
    """
    groups: dict[tuple[str, ObjectClass], list[int]] = defaultdict(list)
    for index, feature in enumerate(features):
        if (
            feature.object_class.is_utility
            and feature.geometry.geom_type == "LineString"
            and not feature.geometry.is_empty
        ):
            groups[feature.layer, feature.object_class].append(index)

    result = list(features)
    for indices in groups.values():
        known = [features[index].diameter_m for index in indices]
        if not any(value is None for value in known) or not any(
            value is not None and math.isfinite(value) and value > 0 for value in known
        ):
            continue
        _fill_chain_group(features, indices, result)
    return tuple(result)


def _fill_chain_group(
    features: tuple[Feature, ...], indices: list[int], result: list[Feature]
) -> None:
    endpoints, neighbours, ambiguous = _chain_topology(features, indices)
    if not _check_chain_intersections(features, indices, endpoints, ambiguous):
        return

    visited: set[int] = set()
    for seed in indices:
        if seed in visited:
            continue
        component: set[int] = set()
        pending = [seed]
        while pending:
            index = pending.pop()
            if index in component:
                continue
            component.add(index)
            pending.extend(neighbours[index] - component)
        visited.update(component)
        if component & ambiguous:
            continue
        diameter = _chain_diameter(features, component, endpoints)
        if diameter is None:
            continue
        for index in component:
            if features[index].diameter_m is None:
                result[index] = replace(features[index], diameter_m=diameter)


def _check_chain_intersections(
    features: tuple[Feature, ...],
    indices: list[int],
    endpoints: dict[int, tuple[tuple[float, float], tuple[float, float]]],
    ambiguous: set[int],
) -> bool:
    """Bound topology work; dense groups keep their existing diameter assignments."""
    tree = STRtree([features[index].geometry for index in indices])
    budget = min(16 * len(indices), 200_000)
    visited_pairs = 0
    for position, index in enumerate(indices):
        candidates = tree.query(features[index].geometry, predicate="intersects")
        visited_pairs += len(candidates)
        if visited_pairs > budget:
            return False
        for other_position in candidates:
            if other_position <= position:
                continue
            other = indices[int(other_position)]
            intersection = features[index].geometry.intersection(features[other].geometry)
            common_ends = set(endpoints[index]) & set(endpoints[other])
            if (
                intersection.geom_type != "Point"
                or tuple(intersection.coords[0][:2]) not in common_ends
            ):
                ambiguous.update((index, other))
    return True


def _chain_topology(
    features: tuple[Feature, ...], indices: list[int]
) -> tuple[
    dict[int, tuple[tuple[float, float], tuple[float, float]]],
    dict[int, set[int]],
    set[int],
]:
    endpoints: dict[int, tuple[tuple[float, float], tuple[float, float]]] = {}
    at_node: dict[tuple[float, float], list[int]] = defaultdict(list)
    neighbours: dict[int, set[int]] = defaultdict(set)
    ambiguous: set[int] = set()
    for index in indices:
        feature = features[index]
        start = tuple(feature.geometry.coords[0][:2])
        end = tuple(feature.geometry.coords[-1][:2])
        endpoints[index] = (start, end)
        at_node[start].append(index)
        at_node[end].append(index)
        if start == end or not feature.geometry.is_simple or feature.geometry_error_m != 0:
            ambiguous.add(index)
    for members in at_node.values():
        if len(members) == _CHAIN_DEGREE:
            left, right = members
            neighbours[left].add(right)
            neighbours[right].add(left)
        elif len(members) > _CHAIN_DEGREE:
            # Do not create a quadratic adjacency list at a crowded junction.
            ambiguous.update(members)
    return endpoints, neighbours, ambiguous


def _chain_diameter(
    features: tuple[Feature, ...],
    component: set[int],
    endpoints: dict[int, tuple[tuple[float, float], tuple[float, float]]],
) -> float | None:
    degrees = Counter(point for index in component for point in endpoints[index])
    if sum(degree == 1 for degree in degrees.values()) != _OPEN_CHAIN_ENDS:
        return None
    diameters = {
        features[index].diameter_m for index in component if features[index].diameter_m is not None
    }
    if len(diameters) != 1:
        return None
    diameter = next(iter(diameters))
    if diameter is None or not math.isfinite(diameter) or diameter <= 0:
        return None
    return diameter
