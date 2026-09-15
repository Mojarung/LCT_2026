"""Привязка подписей диаметров (например, `d=400ж.б.`) к линиям сетей того же слоя."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING

from shapely import STRtree
from shapely.geometry import Point

if TYPE_CHECKING:
    from green.domain.objects import Feature, TextLabel

_DIAMETER = re.compile(r"(?:^|[^a-zа-я])(?:d|ду|ø|ф)\s*=?\s*(\d{2,4})", re.IGNORECASE)
_MIN_MM = 20
_MAX_MM = 4000


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

    return tuple(replace(f, diameter_m=best[i]) if i in best else f for i, f in enumerate(features))
