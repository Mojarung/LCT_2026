"""Fallback for ambiguous dense marks on explicitly named vegetation-strip layers.

This is not proof of individual trunks or shrub species. Recognisable shrub sign 273
is extracted first by shrub_strips; unrelated close individual trees stay individual.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING

from shapely import STRtree
from shapely.geometry import MultiPoint

from green.application.semantic_names import local_name
from green.domain.objects import ClassificationEvidence, ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.domain.objects import Feature

STRIP_METHOD = "tree_strip"
STRIP_SOURCE = "TREE_STRIP"


def chain_tree_strips(
    features: Sequence[Feature], *, spacing_m: float = 1.5
) -> tuple[Feature, ...]:
    """Неопределённые отметки слоя полос группируются по близости; даже одиночная
    отметка этого слоя не доказывает отдельный ствол.

    Полоса - объект `existing_tree` с геометрией MultiPoint: ограничивает посадку тем же
    рисунком. Кружки остаются в сцене с классом ignore и доказательством члена полосы, так что
    учёт каждого примитива не теряется. Экземпляры знаков (DEREVO) и явные уточнения
    пользователя не склеиваются: это настоящие деревья.
    """
    # Filled small marks (REGION/HATCH) can also be graphic dots. Keep their
    # footprint for constraints, but never invent a tree from such a fragment.
    features = tuple(
        replace(
            f,
            source_entity_type=STRIP_SOURCE,
            classification=ClassificationEvidence("tree_strip_unresolved"),
        )
        if _strip_candidate(f)
        and f.geometry.geom_type in {"Polygon", "MultiPolygon"}
        and max(
            f.geometry.bounds[2] - f.geometry.bounds[0], f.geometry.bounds[3] - f.geometry.bounds[1]
        )
        <= 1.0
        else f
        for f in features
    )
    loose = [i for i, f in enumerate(features) if _loose_trunk(f)]
    if not loose:
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
        lf, rf = features[loose[int(left)]], features[loose[int(right)]]
        if (lf.layer, lf.ref.file_sha8, lf.ref.xref_hash8) != (
            rf.layer,
            rf.ref.file_sha8,
            rf.ref.xref_hash8,
        ):
            continue
        a, b = root(int(left)), root(int(right))
        if a != b:
            parent[max(a, b)] = min(a, b)
    chains: dict[int, list[int]] = defaultdict(list)
    for position, index in enumerate(loose):
        chains[root(position)].append(index)
    result = list(features)
    strips = []
    for members in chains.values():
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


def _strip_candidate(feature: Feature) -> bool:
    method = feature.classification.method if feature.classification else ""
    return (
        feature.object_class is ObjectClass.EXISTING_TREE
        and "полос" in local_name(feature.layer).casefold()
        and feature.symbol is None
        and not method.startswith("explicit_")
    )


def _loose_trunk(feature: Feature) -> bool:
    return _strip_candidate(feature) and feature.geometry.geom_type == "Point"
