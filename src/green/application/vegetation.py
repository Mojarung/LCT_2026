"""Перепись растительности: каждое дерево исходника дошло до сцены ровно один раз.

Знаки растительности считаются дважды: независимой переписью вставок в исходнике (её
заполняет инфраструктура) и по якорям классифицированной сцены. Сверка идёт по коду знака,
а не по итоговому классу: явное уточнение пользователя меняет класс, но знак не теряет.
Стволы и полосы, нарисованные кружками без знака, считаются отдельно: их источник - сами
кружки, а их учёт ведёт ридер.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely import STRtree

from green.application.symbols import SymbolRole
from green.application.tree_strips import STRIP_SOURCE
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.application.symbols import SymbolCatalog
    from green.domain.objects import Scene

VEGETATION = (
    ObjectClass.EXISTING_TREE,
    ObjectClass.EXISTING_SHRUB,
    ObjectClass.EXISTING_WOODLAND,
    ObjectClass.LAWN,
)
_ANCHORS = frozenset({"SYMBOL", "SYMBOL_MARKER"})

type Point2 = tuple[float, float]


@dataclass(frozen=True, slots=True)
class CensusRecord:
    """Знак исходника по переписи вставок: код, слой, точка вставки в метрах."""

    base: str
    layer: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class ClassCount:
    object_class: ObjectClass
    source: int
    scene: int
    # Есть в исходнике, нет в сцене; в сцене лишний (удвоен или не из исходника).
    missing: tuple[Point2, ...] = ()
    extra: tuple[Point2, ...] = ()


@dataclass(frozen=True, slots=True)
class VegetationCensus:
    classes: tuple[ClassCount, ...]
    loose_trunks: int = 0
    strips: int = 0
    strip_points: int = 0

    @property
    def matches(self) -> bool:
        return all(not c.missing and not c.extra for c in self.classes)


def vegetation_census(
    records: Sequence[CensusRecord],
    scene: Scene,
    catalog: SymbolCatalog,
    *,
    tolerance_m: float = 1e-3,
) -> VegetationCensus:
    source: dict[ObjectClass, list[Point2]] = defaultdict(list)
    anchors: dict[ObjectClass, list[Point2]] = defaultdict(list)
    for record in records:
        kind = _vegetation(catalog, record.base)
        if kind is not None:
            source[kind].append((record.x, record.y))
    loose = strips = strip_points = 0
    for feature in scene.features:
        geometry = feature.geometry
        if feature.source_entity_type in _ANCHORS and feature.block is not None:
            kind = _vegetation(catalog, feature.block)
            if kind is not None and geometry.geom_type == "Point":
                anchors[kind].append((geometry.x, geometry.y))
        elif feature.source_entity_type == STRIP_SOURCE:
            strips += 1
            strip_points += len(shapely.get_parts(geometry))
        elif feature.object_class is ObjectClass.EXISTING_TREE and geometry.geom_type == "Point":
            loose += 1
    return VegetationCensus(
        classes=tuple(
            _compare(kind, source[kind], anchors[kind], tolerance_m)
            for kind in VEGETATION
            if source[kind] or anchors[kind]
        ),
        loose_trunks=loose,
        strips=strips,
        strip_points=strip_points,
    )


def _vegetation(catalog: SymbolCatalog, block: str) -> ObjectClass | None:
    entry = catalog.get(block)
    if entry is None or entry.role not in {SymbolRole.POINT, SymbolRole.MARKER}:
        return None
    return entry.object_class if entry.object_class in VEGETATION else None


def _compare(
    kind: ObjectClass, source: list[Point2], scene: list[Point2], tolerance_m: float
) -> ClassCount:
    """Пары «знак исходника - якорь сцены» в пределах допуска, каждый якорь один раз."""
    used = np.zeros(len(scene), dtype=bool)
    missing: list[Point2] = []
    points = shapely.points(scene) if scene else np.empty(0, dtype=object)
    tree = STRtree(points) if scene else None
    for x, y in source:
        here = shapely.Point(x, y)
        near = (
            tree.query(here, predicate="dwithin", distance=tolerance_m)
            if tree is not None
            else np.empty(0, dtype=np.int64)
        )
        free = [int(i) for i in near if not used[i]]
        if free:
            # Ближайший свободный, а не первый попавшийся: иначе соседние знаки в пределах
            # допуска разбирались бы накрест и давали ложную пару «потерян - лишний».
            used[min(free, key=lambda i: shapely.distance(here, points[i]))] = True
        else:
            missing.append((round(x, 3), round(y, 3)))
    extra = tuple((round(scene[i][0], 3), round(scene[i][1], 3)) for i in np.flatnonzero(~used))
    return ClassCount(kind, len(source), len(scene), tuple(missing), extra)
