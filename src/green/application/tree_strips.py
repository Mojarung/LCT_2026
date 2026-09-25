"""Полоса деревьев: ряд кружков условного знака - одна полоса, а не десятки стволов.

Знак «Полоса деревьев» Мосгеотреста - кружки через 0,7-0,8 м вдоль полосы (Кустанайская,
24.09.2026). Стволы так часто не растут: шаг посадки деревьев 5-6 м (743-ПП, табл. 3.6.2),
поэтому это рисунок полосы. По стволу на кружок перепись насчитала бы фантомные деревья.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING

from shapely import STRtree
from shapely.geometry import MultiPoint

from green.domain.objects import ClassificationEvidence, ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.domain.objects import Feature

STRIP_METHOD = "tree_strip"
STRIP_SOURCE = "TREE_STRIP"


def chain_tree_strips(
    features: Sequence[Feature], *, spacing_m: float = 1.5, min_points: int = 3
) -> tuple[Feature, ...]:
    """Отдельные стволы ближе `spacing_m` друг к другу цепочкой от `min_points` - одна полоса.

    Полоса - объект `existing_tree` с геометрией MultiPoint: ограничивает посадку тем же
    рисунком. Кружки остаются в сцене с классом ignore и доказательством члена полосы, так что
    учёт каждого примитива не теряется. Экземпляры знаков (DEREVO) и явные уточнения
    пользователя не склеиваются: это настоящие деревья.
    """
    loose = [i for i, f in enumerate(features) if _loose_trunk(f)]
    if len(loose) < min_points:
        return tuple(features)
    points = [features[i].geometry for i in loose]
    near = STRtree(points).query(points, predicate="dwithin", distance=spacing_m)
    parent = list(range(len(points)))

    def root(item: int) -> int:
        while parent[item] != item:
            parent[item] = parent[parent[item]]
            item = parent[item]
        return item

    for left, right in zip(*near, strict=True):
        a, b = root(int(left)), root(int(right))
        if a != b:
            parent[max(a, b)] = min(a, b)
    chains: dict[int, list[int]] = defaultdict(list)
    for position, index in enumerate(loose):
        chains[root(position)].append(index)
    result = list(features)
    strips = []
    for members in chains.values():
        if len(members) < min_points:
            continue
        first = features[members[0]]
        strip_ref = replace(first.ref, handle=f"{first.ref.handle}+strip")
        member_of = ClassificationEvidence(f"tree_strip_member:{strip_ref}")
        for index in members:
            result[index] = replace(
                features[index], object_class=ObjectClass.IGNORE, classification=member_of
            )
        strips.append(
            replace(
                first,
                ref=strip_ref,
                geometry=MultiPoint([features[i].geometry for i in members]),
                source_entity_type=STRIP_SOURCE,
                circle_radius_m=None,
                circle_center_m=None,
                classification=ClassificationEvidence(STRIP_METHOD),
            )
        )
    return (*result, *strips)


def _loose_trunk(feature: Feature) -> bool:
    method = feature.classification.method if feature.classification else ""
    return (
        feature.object_class is ObjectClass.EXISTING_TREE
        and feature.symbol is None
        and feature.geometry.geom_type == "Point"
        and not method.startswith("explicit_")
    )
