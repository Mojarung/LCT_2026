"""Семантика слоёв: сопоставление слоёв и блоков чертежа классам объектов."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from shapely.geometry import Point
from shapely.prepared import prep

from green.application.constraints import work_boundary
from green.application.errors import InputError
from green.application.semantic_names import local_name, material_context_requires_review, name_key
from green.application.surface_labels import classify_labels, label_report_groups
from green.domain.objects import (
    ClassificationEvidence,
    Feature,
    InsertInstance,
    ObjectClass,
    Scene,
    SourceRef,
)

if TYPE_CHECKING:
    import re
    from pathlib import Path

    from green.application.params import PlanParams
    from green.application.surface_labels import LabelGroup


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
    symbol_instance: bool = False

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
    if (
        params
        and params.semantic_source_sha256
        and params.semantic_source_sha256 != scene.source_sha256
    ):
        raise InputError(
            "Уточнения относятся к другому DXF: хеш исходника изменился. "
            "Загрузите review-input.dxf из проверенного прогона или выполните уточнение заново."
        )
    overrides = _Overrides(params)
    cache: dict[tuple[str, str | None, str, bool], tuple[ObjectClass, ClassificationEvidence]] = {}
    classified = []
    for feature in scene.features:
        if feature.uncertain_footprint:
            classified.append(
                replace(
                    feature,
                    object_class=ObjectClass.UNCERTAIN_AREA,
                    classification=ClassificationEvidence("bounded_unreadable_geometry"),
                )
            )
            continue
        if feature.source_entity_type == "WIPEOUT":
            classified.append(
                replace(
                    feature,
                    object_class=ObjectClass.DRAWING_MASK,
                    classification=ClassificationEvidence("entity_type"),
                )
            )
            continue
        if feature.source_entity_type == "IMAGE":
            exact = overrides.maps["feature"].get(name_key(str(feature.ref)))
            if exact is not None and exact[1] is not ObjectClass.IGNORE:
                raise InputError(
                    f"IMAGE {feature.ref}: можно только явно исключить этот растр как "
                    "справочную подложку после проверки исходного изображения и векторных данных"
                )
            classified.append(
                replace(
                    feature,
                    object_class=ObjectClass.IGNORE if exact else ObjectClass.UNKNOWN,
                    classification=ClassificationEvidence(
                        "explicit_feature" if exact else "raster_review_required",
                        override_key=exact[0] if exact else None,
                    ),
                )
            )
            continue
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
    classified = _collapse_tree_symbols(classified, layer_map, params)
    counts = Counter((f.layer, f.object_class) for f in classified)
    coverage = tuple(
        LayerCoverage(layer=layer, object_class=cls, features=n)
        for (layer, cls), n in sorted(counts.items(), key=lambda item: (item[0][0], item[0][1]))
    )
    labels = classify_labels(scene.labels, layer_map, params.label_roles if params else {})
    return replace(scene, features=tuple(classified), labels=labels), coverage


def _collapse_tree_symbols(
    features: list[Feature], layer_map: LayerMap, params: PlanParams | None
) -> list[Feature]:
    """Use the INSERT anchor once; retain refs to every contributing CAD primitive."""
    explicit_tree_blocks = frozenset(
        name_key(name)
        for name, kind in (params.block_classes.items() if params else ())
        if kind == ObjectClass.EXISTING_TREE
    )
    explicit_tree_instances = frozenset(
        name_key(ref)
        for ref, kind in (params.feature_classes.items() if params else ())
        if kind == ObjectClass.EXISTING_TREE
    )
    symbol_rules = frozenset(
        index
        for index, rule in enumerate(layer_map.rules)
        if rule.symbol_instance
        or (rule.target is MatchTarget.BLOCK and rule.object_class is ObjectClass.EXISTING_TREE)
    )
    groups: dict[SourceRef, list[Feature]] = defaultdict(list)
    instances: dict[SourceRef, InsertInstance] = {}
    output: list[Feature | SourceRef] = []
    for feature in features:
        instance = _tree_symbol_instance(
            feature, explicit_tree_blocks, explicit_tree_instances, symbol_rules
        )
        if instance is None:
            output.append(feature)
            continue
        key = instance.ref
        if key not in groups:
            output.append(key)
            instances[key] = instance
        groups[key].append(feature)
    collapsed: dict[SourceRef, Feature] = {}
    for key, parts in groups.items():
        instance = instances[key]
        first = parts[0]
        collapsed[key] = replace(
            first,
            ref=instance.ref,
            block=instance.block,
            geometry=Point(instance.x, instance.y),
            circle_radius_m=max((part.circle_radius_m or 0.0 for part in parts), default=0.0)
            or None,
            circle_center_m=(instance.x, instance.y),
            geometry_error_m=0.0,
            source_entity_type="INSERT",
            symbol_parts=tuple(dict.fromkeys(part.ref for part in parts)),
            symbol_layers=tuple(dict.fromkeys(part.layer for part in parts)),
        )
    return [collapsed[item] if isinstance(item, SourceRef) else item for item in output]


def _tree_symbol_instance(
    feature: Feature,
    explicit_tree_blocks: frozenset[str],
    explicit_tree_instances: frozenset[str],
    symbol_rules: frozenset[int],
) -> InsertInstance | None:
    if feature.object_class is not ObjectClass.EXISTING_TREE or not feature.insert_chain:
        return None
    for instance in reversed(feature.insert_chain):
        if name_key(str(instance.ref)) in explicit_tree_instances:
            return instance
    for instance in reversed(feature.insert_chain):
        if name_key(instance.block) in explicit_tree_blocks:
            return instance
    evidence = feature.classification
    if (
        evidence
        and evidence.method == "name_rule"
        and symbol_rules.intersection(evidence.chosen_rules)
    ):
        # A layer-0 decorative child inherits the outer sign's semantic layer.
        # The nearest INSERT that actually declares this layer is its anchor.
        for instance in reversed(feature.insert_chain):
            if instance.declared_layer != "0" and name_key(instance.declared_layer) == name_key(
                feature.layer
            ):
                return instance
        return feature.insert_chain[-1]
    return None


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
    elif (
        kind in {ObjectClass.CURB, ObjectClass.PAVEMENT_EDGE, ObjectClass.FENCE}
        and geometry.geom_type in {"Polygon", "MultiPolygon"}
        and feature.source_entity_type in {"LWPOLYLINE", "POLYLINE", "CIRCLE", "ELLIPSE"}
    ):
        # These classes denote an edge/enclosure, not a filled obstacle. A
        # closed CAD polyline arrives as a polygon until semantics are known;
        # measuring to its filled interior would forbid every enclosed plant.
        # Area classes and explicit HATCH/MPOLYGON fills keep their interiors.
        geometry = geometry.boundary
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
        entry = self.maps["feature"].get(name_key(str(feature.ref)))
        if entry is not None:
            key, kind = entry
            return kind, "explicit_feature", key
        for instance in reversed(feature.insert_chain):
            entry = self.maps["feature"].get(name_key(str(instance.ref)))
            if entry is not None:
                key, kind = entry
                return kind, "explicit_feature", key
        for block in (
            *(instance.block for instance in reversed(feature.insert_chain)),
            feature.block,
        ):
            entry = self.maps["block"].get(name_key(block)) if block is not None else None
            if entry is not None:
                key, kind = entry
                return kind, "explicit_block", key
        entry = self.maps["layer"].get(name_key(feature.layer))
        if entry is not None:
            key, kind = entry
            return kind, "explicit_layer", key
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
    work_intersections: int | None = None


@dataclass(frozen=True, slots=True)
class RuleDescription:
    index: int
    pattern: str
    target: MatchTarget
    geometry: GeometryKind
    object_class: ObjectClass
    priority: int
    seen_in_pilot: bool
    symbol_instance: bool = False


@dataclass(frozen=True, slots=True)
class ClassificationReport:
    source_sha256: str
    layer_map_fingerprint: str
    features: int
    unresolved_features: int
    groups: tuple[ClassificationGroup, ...]
    rules: tuple[RuleDescription, ...]
    unused_overrides: tuple[str, ...]
    work_boundary_present: bool = False
    unresolved_work_intersections: int | None = None
    labels: int = 0
    excluded_surface_labels: int = 0
    label_groups: tuple[LabelGroup, ...] = ()
    scope: str = (
        "Semantic assignments of imported geometry and label roles only. "
        "Name matches and explicit assignments "
        "are assumptions, not measured accuracy or evidence that the survey is complete. "
        "seen_in_pilot records historical observation, not confirmation for this drawing. "
        "Reference samples contain at most five objects per group."
        " Work intersections count features touching the currently classified "
        "work boundary; they do not make objects outside it safe to ignore."
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
        "layer": {
            name_key(layer)
            for feature in scene.features
            for layer in (feature.layer, *feature.symbol_layers)
        },
        "block": {
            name_key(name)
            for feature in scene.features
            for name in (
                *(instance.block for instance in feature.insert_chain),
                feature.block,
            )
            if name is not None
        },
        "feature": {
            name_key(str(ref))
            for feature in scene.features
            for ref in (
                feature.ref,
                *(instance.ref for instance in feature.insert_chain),
                *feature.symbol_parts,
            )
        },
    }
    unused = tuple(
        f"{target}_classes:{key}"
        for target, names in available.items()
        for key in getattr(params, f"{target}_classes", {})
        if name_key(key) not in names
    )
    label_refs = {name_key(str(label.ref)) for label in scene.labels}
    unused += tuple(
        f"label_roles:{key}"
        for key in getattr(params, "label_roles", {})
        if name_key(key) not in label_refs
    )
    boundary = work_boundary(scene.features)
    intersections: Counter[tuple[str, str | None, str, ObjectClass, ClassificationEvidence]] = (
        Counter()
    )
    unresolved_work: int | None = None
    if boundary is not None:
        prepared = prep(boundary)
        unresolved_work = 0
        for key, items in groups.items():
            intersections[key] = sum(prepared.intersects(item.geometry) for item in items)
            if key[3] in {ObjectClass.UNKNOWN, ObjectClass.UTILITY_UNKNOWN}:
                unresolved_work += intersections[key]
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
                intersections[key] if boundary is not None else None,
            )
            for key, items in groups.items()
        ),
        rules=tuple(
            RuleDescription(
                i,
                r.pattern.pattern,
                r.target,
                r.geometry,
                r.object_class,
                r.priority,
                r.confirmed,
                r.symbol_instance,
            )
            for i, r in enumerate(layer_map.rules)
        ),
        unused_overrides=unused,
        work_boundary_present=boundary is not None,
        unresolved_work_intersections=unresolved_work,
        labels=len(scene.labels),
        excluded_surface_labels=sum(label.surface_role == "ignore" for label in scene.labels),
        label_groups=label_report_groups(scene.labels),
    )


class ClassificationError(InputError):
    def __init__(
        self, report: ClassificationReport, scene: Scene | None = None, source: Path | None = None
    ) -> None:
        self.report = report
        self.scene = scene
        self.source = source
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


def require_classified(
    report: ClassificationReport,
    params: PlanParams,
    *,
    scene: Scene | None = None,
    source: Path | None = None,
) -> None:
    if report.unused_overrides or (params.require_known_objects and not report.ready):
        raise ClassificationError(report, scene, source)
