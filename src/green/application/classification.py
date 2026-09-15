"""Семантика слоёв: сопоставление слоёв и блоков чертежа классам объектов."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from green.domain.objects import Feature, ObjectClass, Scene

if TYPE_CHECKING:
    import re


class MatchTarget(StrEnum):
    LAYER = "layer"
    BLOCK = "block"


class GeometryKind(StrEnum):
    """Фильтр по типу геометрии: на одном слое топоплана бывают и стволы, и контур полосы."""

    ANY = "any"
    POINT = "point"
    LINE = "line"
    AREA = "area"


_KIND_OF_TYPE = {
    "Point": GeometryKind.POINT,
    "MultiPoint": GeometryKind.POINT,
    "LineString": GeometryKind.LINE,
    "MultiLineString": GeometryKind.LINE,
    "Polygon": GeometryKind.AREA,
    "MultiPolygon": GeometryKind.AREA,
}


@dataclass(frozen=True, slots=True)
class LayerRule:
    pattern: re.Pattern[str]
    target: MatchTarget
    object_class: ObjectClass
    confirmed: bool
    geometry: GeometryKind = GeometryKind.ANY

    def matches(self, feature: Feature) -> bool:
        value = feature.block if self.target is MatchTarget.BLOCK else feature.layer
        if value is None or not self.pattern.search(value):
            return False
        return (
            self.geometry is GeometryKind.ANY
            or _KIND_OF_TYPE.get(feature.geometry.geom_type) is self.geometry
        )


@dataclass(frozen=True, slots=True)
class LayerMap:
    """Упорядоченный список правил: побеждает первое совпавшее."""

    rules: tuple[LayerRule, ...]
    fingerprint: str

    def classify(self, feature: Feature) -> ObjectClass:
        for rule in self.rules:
            if rule.matches(feature):
                return rule.object_class
        return ObjectClass.UNKNOWN


@dataclass(frozen=True, slots=True)
class LayerCoverage:
    layer: str
    object_class: ObjectClass
    features: int


def classify_scene(scene: Scene, layer_map: LayerMap) -> tuple[Scene, tuple[LayerCoverage, ...]]:
    """Присваивает классы всем объектам и возвращает отчёт покрытия по слоям."""
    classified = tuple(replace(f, object_class=layer_map.classify(f)) for f in scene.features)
    counts = Counter((f.layer, f.object_class) for f in classified)
    coverage = tuple(
        LayerCoverage(layer=layer, object_class=cls, features=n)
        for (layer, cls), n in sorted(counts.items(), key=lambda item: (item[0][0], item[0][1]))
    )
    return replace(scene, features=classified), coverage


def promote_unknown_lines(scene: Scene) -> Scene:
    """Fail-closed: нераспознанные линии считаются сетью неизвестного типа."""
    line_types = {"LineString", "MultiLineString"}
    features = tuple(
        replace(f, object_class=ObjectClass.UTILITY_UNKNOWN)
        if f.object_class is ObjectClass.UNKNOWN and f.geometry.geom_type in line_types
        else f
        for f in scene.features
    )
    return replace(scene, features=features)
