"""Похоже ли место посадки на практику проектировщиков: скоркарта по расстояниям до объектов.

Команда LPN1KoL учила перцептрон на посадках проектировщиков пилота (AUC 0,63 против 0,54 у
эвристики). Здесь та же идея без чёрного ящика: логистическая регрессия по корзинам расстояний
(«до борта 2-3 м: +0,77», «на газоне: +1,4»), обученная на новых деревьях проектировщиков 12 улиц
пилота против случайных мест той же улицы (tools/research/ml/exp_placement_scorecard.py, AUC
0,72 на 4 отложенных улицах против 0,65 у эвристики «газон у борта»). Коэффициенты лежат в
config/likeness.json и печатаются как есть.

Скоркарта не решает, где сажать: нормы отсекают места раньше, а в задаче выбора мест она
только добавляет к весу места до likeness_weight очков - меньше, чем стоит одно лишнее место.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature

CAP_M = 40.0
LAWN_TERM = "на газоне"


@dataclass(frozen=True, slots=True)
class LikenessModel:
    """Скоркарта: корзины расстояний по классам, слагаемые и свободный член логита."""

    classes: tuple[str, ...]
    edges: tuple[float, ...]
    terms: Mapping[str, float]
    intercept: float
    depth_edges: tuple[float, ...] = (0.0, 1.0, 2.0, 4.0)
    _cache: dict[int, object] = field(default_factory=dict, compare=False, repr=False)

    def probability(
        self, xy: NDArray[np.float64], features: Sequence[Feature]
    ) -> NDArray[np.float64]:
        """Вероятность «так посадил бы проектировщик» для каждой точки (0..1)."""
        if not len(xy):
            return np.zeros(0)
        logit = np.full(len(xy), self.intercept)
        trees, lawn = self._layers(features)
        points = shapely.points(xy)
        for name in self.classes:
            tree = trees.get(name)
            if tree is None:
                distance = np.full(len(xy), CAP_M)
            else:
                _, distance = tree.query_nearest(points, return_distance=True, all_matches=False)
                distance = np.minimum(np.nan_to_num(distance, nan=CAP_M), CAP_M)
            logit += self._binned(name, distance)
        if lawn is not None:
            inside = shapely.contains_xy(lawn, xy[:, 0], xy[:, 1])
            depth = np.where(inside, shapely.distance(lawn.boundary, points), 0.0)
            logit += inside * self.terms.get(LAWN_TERM, 0.0)
            for lo, hi in zip(self.depth_edges, (*self.depth_edges[1:], math.inf), strict=True):
                key = f"глубина в газоне {lo:g}-{_upper(hi)} м"
                logit += inside * (depth >= lo) * (depth < hi) * self.terms.get(key, 0.0)
        return 1.0 / (1.0 + np.exp(-logit))

    def _binned(self, name: str, distance: NDArray[np.float64]) -> NDArray[np.float64]:
        out = np.zeros(len(distance))
        bounds = (*self.edges, CAP_M + 1e-6)
        for lo, hi in itertools.pairwise(bounds):
            weight = self.terms.get(f"{name} {lo:g}-{min(hi, CAP_M):g} м", 0.0)
            out += ((distance >= lo) & (distance < hi)) * weight
        return out

    def _layers(
        self, features: Sequence[Feature]
    ) -> tuple[dict[str, shapely.STRtree], BaseGeometry | None]:
        key = id(features)
        cached = self._cache.get(key)
        if cached is not None and cached[0] is features:  # ty: ignore[not-subscriptable]
            return cached[1], cached[2]  # ty: ignore[not-subscriptable]
        groups: dict[str, list] = {}
        lawns = []
        for feature in features:
            name = feature.object_class.value
            if name in self.classes:
                groups.setdefault(name, []).append(feature.geometry)
            if feature.object_class is ObjectClass.LAWN and feature.geometry.area > 0:
                lawns.append(feature.geometry)
        trees = {name: shapely.STRtree(items) for name, items in groups.items()}
        lawn = shapely.union_all(lawns) if lawns else None
        if lawn is not None:
            shapely.prepare(lawn)
        self._cache.clear()
        self._cache[key] = (features, trees, lawn)
        return trees, lawn


def _upper(value: float) -> str:
    return "1e+09" if math.isinf(value) else f"{value:g}"


def likeness_model(data: Mapping[str, object]) -> LikenessModel:
    """Скоркарта из разобранного config/likeness.json."""
    return LikenessModel(
        classes=tuple(str(c) for c in data["classes"]),  # ty: ignore[not-iterable]
        edges=tuple(float(e) for e in data["edges"]),  # ty: ignore[not-iterable]
        terms={str(k): float(v) for k, v in data["terms"].items()},  # ty: ignore[unresolved-attribute]
        intercept=float(data["intercept"]),  # ty: ignore[invalid-argument-type]
    )
