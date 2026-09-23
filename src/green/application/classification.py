"""Семантика слоёв: сопоставление слоёв и блоков чертежа классам объектов."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from shapely.geometry import Point

from green.application.errors import InputError
from green.domain.objects import ClassificationEvidence, Feature, ObjectClass, Scene

if TYPE_CHECKING:
    from green.application.params import PlanParams


def name_key(value: str) -> str:
    """CAD names are case-insensitive; Unicode spelling must not change a decision."""
    return unicodedata.normalize("NFC", value).casefold()


def local_name(value: str) -> str:
    """XREF filenames are namespaces, not semantic labels of their children."""
    return re.split(r"\||\$\d+\$", unicodedata.normalize("NFC", value))[-1]


# Detect reasons to ask for a per-input assignment, never to grant soil. This is
# deliberately not a universal construction-language parser: unseen wording
# remains an explicit limitation of automatic name rules.
_MATERIAL_CONTEXT = re.compile(
    r"\b(?:за|вместо|на месте|не|нет|без)\b|"
    r"\b(?:демонт|уничтож|снос|проектир|восстан|устройств|замен|новый|нового|новая|новое)|"
    r"\b(?:proposed|demolition|remove|removed|replace|replacement|new|not)\b|"
    r"\bгазон\s+[ру]\b|\bдв гп п газон\b",
    re.IGNORECASE,
)


def material_context_requires_review(*names: str | None) -> bool:
    """Work/negation wording cannot establish the material of a planting area."""
    return any(
        _MATERIAL_CONTEXT.search(re.sub(r"[_\-]+", " ", local_name(name))) for name in names if name
    )


class MatchTarget(StrEnum):
    LAYER = "layer"
    BLOCK = "block"


class GeometryKind(StrEnum):
    """Фильтр по типу геометрии: на одном слое топоплана бывают и стволы, и контур полосы."""

    ANY = "any"
    POINT = "point"
    LINE = "line"
    AREA = "area"
    CIRCLE = "circle"


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
    priority: int = 0

    def matches(self, feature: Feature) -> bool:
        value = feature.block if self.target is MatchTarget.BLOCK else feature.layer
        if value is None or not self.pattern.search(local_name(value)):
            return False
        return (
            self.geometry is GeometryKind.ANY
            or (self.geometry is GeometryKind.CIRCLE and feature.circle_radius_m is not None)
            or _KIND_OF_TYPE.get(feature.geometry.geom_type) is self.geometry
        )


@dataclass(frozen=True, slots=True)
class LayerMap:
    """Conflicting rules at the same explicit priority leave the object unknown."""

    rules: tuple[LayerRule, ...]
    fingerprint: str

    def classify(self, feature: Feature) -> ObjectClass:
        return self.decide(feature)[0]

    def decide(self, feature: Feature) -> tuple[ObjectClass, ClassificationEvidence]:
        matches = tuple(i for i, rule in enumerate(self.rules) if rule.matches(feature))
        if not matches:
            return ObjectClass.UNKNOWN, ClassificationEvidence("unmatched")
        # A named symbol (e.g. a well on the water layer) has more specific meaning.
        blocks = tuple(i for i in matches if self.rules[i].target is MatchTarget.BLOCK)
        candidates = blocks or matches
        priority = max(self.rules[i].priority for i in candidates)
        chosen = tuple(i for i in candidates if self.rules[i].priority == priority)
        kinds = {self.rules[i].object_class for i in chosen}
        if len(kinds) != 1:
            return ObjectClass.UNKNOWN, ClassificationEvidence("conflict", matches, chosen)
        kind = next(iter(kinds))
        if kind is ObjectClass.LAWN and material_context_requires_review(
            feature.layer, feature.block
        ):
            return ObjectClass.UNKNOWN, ClassificationEvidence("material_context", matches, chosen)
        return kind, ClassificationEvidence("name_rule", matches, chosen)


@dataclass(frozen=True, slots=True)
class LayerCoverage:
    layer: str
    object_class: ObjectClass
    features: int


def classify_scene(
    scene: Scene, layer_map: LayerMap, params: PlanParams | None = None
) -> tuple[Scene, tuple[LayerCoverage, ...]]:
    """Присваивает классы всем объектам и возвращает отчёт покрытия по слоям."""
    overrides = _Overrides(params)
    cache: dict[tuple[str, str | None, str, bool], tuple[ObjectClass, ClassificationEvidence]] = {}
    classified = []
    for feature in scene.features:
        key = (
            feature.layer,
            feature.block,
            feature.geometry.geom_type,
            feature.circle_radius_m is not None,
        )
        if key not in cache:
            cache[key] = layer_map.decide(feature)
        kind, evidence = cache[key]
        explicit = overrides.decide(feature)
        if explicit is not None:
            kind, method, override_key = explicit
            evidence = ClassificationEvidence(method, evidence.matched_rules, (), override_key)
        classified.append(_classify_feature(feature, kind, evidence))
    counts = Counter((f.layer, f.object_class) for f in classified)
    coverage = tuple(
        LayerCoverage(layer=layer, object_class=cls, features=n)
        for (layer, cls), n in sorted(counts.items(), key=lambda item: (item[0][0], item[0][1]))
    )
    return replace(scene, features=tuple(classified)), coverage


def _classify_feature(
    feature: Feature, kind: ObjectClass, evidence: ClassificationEvidence
) -> Feature:
    # Only semantic evidence that this is an existing tree makes the circle a
    # crown symbol with a trunk at its centre. Generic circles keep their area.
    geometry = feature.geometry
    error = feature.geometry_error_m
    if kind is ObjectClass.EXISTING_TREE and feature.circle_radius_m is not None:
        if feature.circle_center_m is not None:
            geometry = Point(feature.circle_center_m)
            error = 0.0
        else:
            geometry = geometry.centroid
    return replace(
        feature,
        object_class=kind,
        geometry=geometry,
        classification=evidence,
        geometry_error_m=error,
    )


def promote_unknown_lines(scene: Scene) -> Scene:
    """Legacy exploratory assumption; a 2 m buffer does not resolve unknown semantics."""
    line_types = {"LineString", "MultiLineString"}
    features = tuple(
        replace(f, object_class=ObjectClass.UTILITY_UNKNOWN)
        if f.object_class is ObjectClass.UNKNOWN and f.geometry.geom_type in line_types
        else f
        for f in scene.features
    )
    return replace(scene, features=features)


class _Overrides:
    def __init__(self, params: PlanParams | None) -> None:
        self.maps: dict[str, dict[str, tuple[str, ObjectClass]]] = {}
        for target in ("feature", "block", "layer"):
            values = getattr(params, f"{target}_classes", {})
            mapping = {}
            for key, value in values.items():
                canonical = name_key(key)
                if not canonical or canonical in mapping:
                    raise InputError(f"{target}_classes: пустое или повторное имя {key!r}")
                try:
                    mapping[canonical] = (key, ObjectClass(value))
                except ValueError as error:
                    raise InputError(f"{target}_classes: неизвестный класс {value!r}") from error
            self.maps[target] = mapping

    def decide(self, feature: Feature) -> tuple[ObjectClass, str, str] | None:
        for target, value in (
            ("feature", str(feature.ref)),
            ("block", feature.block),
            ("layer", feature.layer),
        ):
            entry = self.maps[target].get(name_key(value)) if value is not None else None
            if entry is not None:
                key, kind = entry
                return kind, f"explicit_{target}", key
        return None


@dataclass(frozen=True, slots=True)
class ClassificationGroup:
    layer: str
    block: str | None
    geometry: str
    object_class: ObjectClass
    evidence: ClassificationEvidence
    features: int
    source_refs: tuple[str, ...]
    max_geometry_error_m: float | None


@dataclass(frozen=True, slots=True)
class RuleDescription:
    index: int
    pattern: str
    target: MatchTarget
    geometry: GeometryKind
    object_class: ObjectClass
    priority: int
    seen_in_pilot: bool


@dataclass(frozen=True, slots=True)
class ClassificationReport:
    source_sha256: str
    layer_map_fingerprint: str
    features: int
    unresolved_features: int
    groups: tuple[ClassificationGroup, ...]
    rules: tuple[RuleDescription, ...]
    unused_overrides: tuple[str, ...]
    scope: str = (
        "Semantic assignments of imported geometry only. Name matches and explicit assignments "
        "are assumptions, not measured accuracy or evidence that the survey is complete. "
        "seen_in_pilot records historical observation, not confirmation for this drawing. "
        "Reference samples contain at most five objects per group."
    )

    @property
    def ready(self) -> bool:
        return not self.unresolved_features and not self.unused_overrides


def classification_report(
    scene: Scene, layer_map: LayerMap, params: PlanParams | None = None
) -> ClassificationReport:
    groups: dict[
        tuple[str, str | None, str, ObjectClass, ClassificationEvidence], list[Feature]
    ] = defaultdict(list)
    unresolved = 0
    for feature in scene.features:
        evidence = feature.classification or ClassificationEvidence("unmatched")
        if feature.object_class in {ObjectClass.UNKNOWN, ObjectClass.UTILITY_UNKNOWN}:
            unresolved += 1
        groups[
            (
                feature.layer,
                feature.block,
                feature.geometry.geom_type,
                feature.object_class,
                evidence,
            )
        ].append(feature)
    # An overridden assignment can legitimately shadow a broader override. Check
    # whether every key names an actual input object, not whether it won precedence.
    available = {
        "layer": {name_key(f.layer) for f in scene.features},
        "block": {name_key(f.block) for f in scene.features if f.block is not None},
        "feature": {name_key(str(f.ref)) for f in scene.features},
    }
    unused = tuple(
        f"{target}_classes:{key}"
        for target, names in available.items()
        for key in getattr(params, f"{target}_classes", {})
        if name_key(key) not in names
    )
    return ClassificationReport(
        source_sha256=scene.source_sha256,
        layer_map_fingerprint=layer_map.fingerprint,
        features=len(scene.features),
        unresolved_features=unresolved,
        groups=tuple(
            ClassificationGroup(
                *key,
                len(items),
                tuple(str(f.ref) for f in items[:5]),
                None
                if any(f.geometry_error_m is None for f in items)
                else max(f.geometry_error_m or 0.0 for f in items),
            )
            for key, items in groups.items()
        ),
        rules=tuple(
            RuleDescription(
                i, r.pattern.pattern, r.target, r.geometry, r.object_class, r.priority, r.confirmed
            )
            for i, r in enumerate(layer_map.rules)
        ),
        unused_overrides=unused,
    )


class ClassificationError(InputError):
    def __init__(self, report: ClassificationReport) -> None:
        self.report = report
        examples = ", ".join(
            dict.fromkeys(
                group.layer
                for group in report.groups
                if group.object_class in {ObjectClass.UNKNOWN, ObjectClass.UTILITY_UNKNOWN}
            )
        )[:500]
        super().__init__(
            f"Требуется уточнить классы объектов: {report.unresolved_features}; слои: {examples}. "
            f"Не найдены соответствия: {', '.join(report.unused_overrides[:5]) or 'нет'}. "
            "См. classification.json; задайте layer_classes, block_classes или feature_classes."
        )


def require_classified(report: ClassificationReport, params: PlanParams) -> None:
    if report.unused_overrides or (params.require_known_objects and not report.ready):
        raise ClassificationError(report)
