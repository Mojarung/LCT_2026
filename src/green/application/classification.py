"""Семантика слоёв: сопоставление слоёв и блоков чертежа классам объектов."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING

import shapely
from shapely.geometry import Point, Polygon

from green.application.errors import InputError
from green.application.name_semantics import Vocabulary
from green.application.semantic_names import (
    base_name,
    local_name,
    material_context_requires_review,
    name_key,
)
from green.application.surface_labels import classify_labels, label_report_groups
from green.application.symbols import SymbolCatalog, SymbolEntry, SymbolRole
from green.application.tree_strips import chain_tree_strips
from green.domain.objects import ClassificationEvidence, Feature, ObjectClass, Scene

if TYPE_CHECKING:
    import re
    from collections.abc import Iterable, Mapping
    from pathlib import Path

    from shapely.geometry.base import BaseGeometry

    from green.application.params import PlanParams
    from green.application.surface_labels import LabelGroup
    from green.domain.objects import SymbolInstance


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
    # Почему объекты слоя не участвуют в расчёте (для ignore обязательна в layer_map.yaml).
    reason: str = ""

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
    # Словарь условных знаков (config/symbols.yaml): знак решает раньше слоя.
    symbols: SymbolCatalog = field(default_factory=SymbolCatalog)
    # Слова имён (config/vocabulary.yaml): вывод для незнакомого, когда правила молчат.
    vocabulary: Vocabulary = field(default_factory=Vocabulary)

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
    """Присваивает классы всем объектам и возвращает отчёт покрытия по слоям.

    Порядок: словарь знаков, правила слоёв, затем для незнакомого (задача 14) вывод по словам
    имени блока и слоя и осторожная замена по геометрии; параметр infer_unknown=False
    оставляет незнакомое неизвестным, и строгий прогон остановится, как задумано проверкой.
    """
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
    infer = params.infer_unknown if params else True
    entries = _symbol_entries(scene.symbols, layer_map, infer=infer)
    instances = {str(symbol.ref): symbol for symbol in scene.symbols}
    cache: dict[tuple[str, str | None, str, bool], tuple[ObjectClass, ClassificationEvidence]] = {}
    classified = []
    for feature in scene.features:
        decided = _stroke_decision(feature, instances, entries, active=bool(layer_map.symbols))
        if decided is None:
            key = (
                feature.layer,
                feature.block,
                feature.geometry.geom_type,
                feature.circle_radius_m is not None,
            )
            if key not in cache:
                cache[key] = layer_map.decide(feature)
                if infer and cache[key][0] is ObjectClass.UNKNOWN:
                    cache[key] = _inferred(feature, layer_map.vocabulary, cache[key][1])
            decided = cache[key]
            if infer and decided[0] is ObjectClass.UNKNOWN:
                decided = _assumed(feature, decided[1])
        kind, evidence = decided
        explicit = overrides.decide(feature)
        if explicit is not None:
            kind, method, override_key = explicit
            evidence = ClassificationEvidence(method, evidence.matched_rules, (), override_key)
        classified.append(_classify_feature(feature, kind, evidence))
    strokes: dict[str, list[BaseGeometry]] = defaultdict(list)
    for feature in scene.features:
        if feature.symbol is not None:
            strokes[feature.symbol].append(feature.geometry)
    classified.extend(_symbol_features(scene.symbols, entries, overrides, strokes))
    classified = list(chain_tree_strips(classified))
    counts = Counter((f.layer, f.object_class) for f in classified)
    coverage = tuple(
        LayerCoverage(layer=layer, object_class=cls, features=n)
        for (layer, cls), n in sorted(counts.items(), key=lambda item: (item[0][0], item[0][1]))
    )
    labels = classify_labels(scene.labels, layer_map, params.label_roles if params else {})
    return replace(scene, features=tuple(classified), labels=labels), coverage


# Малый круг без смысла - предмет в точке (колонка, столбик, ствол): препятствие, а не контур.
_SMALL_CIRCLE_M = 1.5
# Рамка листа Мосгеотреста на слое «0» ссылки (Камчатская: прямоугольник 250 x 400 м с
# легендой и штампом): отрезок или прямоугольник строго по осям координат от 100 м. Съёмка
# так не рисует - борт и край газона по осям на 100 м не идут; контуром рамка резала бы газоны
# по границам листов.
_FRAME_M = 100.0
_AXIS_TOLERANCE_M = 1e-6
_POINT_CLASSES = frozenset(
    {
        ObjectClass.EXISTING_TREE,
        ObjectClass.EXISTING_SHRUB,
        ObjectClass.UTILITY_ACCESS,
        ObjectClass.POLE,
    }
)
_MARKER_CLASSES = frozenset({ObjectClass.LAWN, ObjectClass.EXISTING_WOODLAND})


def _inferred(
    feature: Feature, vocabulary: Vocabulary, previous: ClassificationEvidence
) -> tuple[ObjectClass, ClassificationEvidence]:
    """Вывод по словам имени блока и слоя; совпавшие правила остаются в основании."""
    found = vocabulary.infer(feature.block, feature.layer)
    if found is None:
        return ObjectClass.UNKNOWN, previous
    return found.object_class, ClassificationEvidence(
        found.method, previous.matched_rules, previous.chosen_rules
    )


def _assumed(
    feature: Feature, previous: ClassificationEvidence
) -> tuple[ObjectClass, ClassificationEvidence]:
    """Осторожная замена по геометрии, когда слов нет: точка - отметка, малый круг - предмет,
    остальное - контур, который разделяет покрытия, но отступа не даёт."""
    if feature.geometry.geom_type in {"Point", "MultiPoint"}:
        kind, method = ObjectClass.IGNORE, "assumed_geometry:point"
    elif _sheet_frame(feature.geometry):
        kind, method = ObjectClass.IGNORE, "assumed_geometry:sheet_frame"
    elif feature.circle_radius_m is not None and feature.circle_radius_m <= _SMALL_CIRCLE_M:
        kind, method = ObjectClass.OBSTACLE, "assumed_geometry:small_circle"
    else:
        kind, method = ObjectClass.CONTOUR, "assumed_geometry:contour"
    return kind, ClassificationEvidence(method, previous.matched_rules, previous.chosen_rules)


def _sheet_frame(geometry: BaseGeometry) -> bool:
    """Отрезок или прямоугольник строго по осям координат со стороной от 100 м."""
    if geometry.geom_type == "Polygon":
        x0, y0, x1, y1 = geometry.bounds
        return (
            min(x1 - x0, y1 - y0) >= _FRAME_M
            and len(geometry.interiors) == 0
            and abs(geometry.area - (x1 - x0) * (y1 - y0)) <= _AXIS_TOLERANCE_M * geometry.area
        )
    if geometry.geom_type == "LineString":
        coords = list(geometry.coords)
        if len(coords) == 2:  # noqa: PLR2004 - отрезок
            (ax, ay), (bx, by) = coords[0][:2], coords[1][:2]
            axis = abs(ax - bx) <= _AXIS_TOLERANCE_M or abs(ay - by) <= _AXIS_TOLERANCE_M
            return axis and geometry.length >= _FRAME_M
        if coords[0] == coords[-1] and len(coords) >= 4:  # noqa: PLR2004 - замкнутая ломаная
            return _sheet_frame(Polygon(coords))
    return False


def _symbol_role(kind: ObjectClass) -> SymbolRole:
    if kind in _POINT_CLASSES:
        return SymbolRole.POINT
    if kind in _MARKER_CLASSES:
        return SymbolRole.MARKER
    if kind is ObjectClass.IGNORE:
        return SymbolRole.ANNOTATION
    return SymbolRole.GEOMETRY


def _symbol_entries(
    symbols: Iterable[SymbolInstance], layer_map: LayerMap, *, infer: bool
) -> dict[str, tuple[SymbolEntry, str]]:
    """Запись словаря знаков для каждого экземпляра и основание.

    Незнакомый код - вывод по словам имени блока, затем слоя («Урна_Город» - препятствие,
    блок на слое «Деревья_сущ» - дерево); без слов - препятствие в точке: небольшой знак на
    земле, на который не сажают. Без словаря знаков экземпляры не разбираются вовсе.
    """
    catalog = layer_map.symbols
    if not catalog:
        return {}
    entries: dict[str, tuple[SymbolEntry, str]] = {}
    guessed: dict[tuple[str, str], tuple[SymbolEntry, str]] = {}
    for symbol in symbols:
        code = base_name(symbol.block)
        entry = catalog.get(symbol.block)
        if entry is not None:
            entries[str(symbol.ref)] = (entry, "")
            continue
        if not infer:
            continue
        key = (code, symbol.layer)
        if key not in guessed:
            found = layer_map.vocabulary.infer(symbol.block, symbol.layer)
            guessed[key] = (
                (
                    SymbolEntry(ObjectClass.OBSTACLE, SymbolRole.POINT, confirmed=False),
                    f"symbol_assumed:{code}",
                )
                if found is None
                else (
                    SymbolEntry(
                        found.object_class,
                        _symbol_role(found.object_class),
                        confirmed=False,
                        note=found.method,
                    ),
                    f"symbol_inferred:{code}:{found.word}",
                )
            )
        entries[str(symbol.ref)] = guessed[key]
    return entries


def _stroke_decision(
    feature: Feature,
    instances: Mapping[str, SymbolInstance],
    entries: Mapping[str, tuple[SymbolEntry, str]],
    *,
    active: bool,
) -> tuple[ObjectClass, ClassificationEvidence] | None:
    """Штрих условного знака: класс решает словарь знаков, а не слой.

    Штрих знака-точки, маркера или оформления - рисунок, а не объект: объектом становится сам
    экземпляр знака (_symbol_features). Незнакомый знак без вывода (infer_unknown=False)
    оставляет штрихи неизвестными, и строгий прогон остановится.
    """
    if not active or feature.symbol is None:
        return None
    instance = instances.get(feature.symbol)
    if instance is None:
        return None
    code = base_name(instance.block)
    resolved = entries.get(feature.symbol)
    if resolved is None:
        return ObjectClass.UNKNOWN, ClassificationEvidence(f"symbol_unknown:{code}")
    entry, method = resolved
    if entry.role is SymbolRole.GEOMETRY:
        return entry.object_class, ClassificationEvidence(method or f"symbol_geometry:{code}")
    return ObjectClass.IGNORE, ClassificationEvidence(f"symbol_stroke:{code}")


def _symbol_features(
    symbols: Iterable[SymbolInstance],
    entries: Mapping[str, tuple[SymbolEntry, str]],
    overrides: _Overrides,
    strokes: Mapping[str, list[BaseGeometry]],
) -> list[Feature]:
    """Экземпляр знака-точки или знака-маркера - один объект подосновы в точке вставки.

    Дерево, куст, опора - точка: нормы меряют от ствола и оси. Колодец - контур нарисованного
    знака: отступ считается от наружной стенки, точка в центре занизила бы его на радиус.
    """
    features = []
    for symbol in symbols:
        resolved = entries.get(str(symbol.ref))
        if resolved is None or resolved[0].role not in {SymbolRole.POINT, SymbolRole.MARKER}:
            continue
        entry, method = resolved
        kind = entry.object_class
        evidence = ClassificationEvidence(
            method or f"symbol_{entry.role}:{base_name(symbol.block)}"
        )
        drawn = strokes.get(str(symbol.ref))
        geometry = (
            shapely.union_all(drawn).convex_hull
            if kind is ObjectClass.UTILITY_ACCESS and drawn
            else Point(symbol.x, symbol.y)
        )
        feature = Feature(
            ref=symbol.ref,
            layer=symbol.layer,
            geometry=geometry,
            block=symbol.block,
            source_entity_type="SYMBOL" if entry.role is SymbolRole.POINT else "SYMBOL_MARKER",
            symbol=str(symbol.ref),
        )
        explicit = overrides.decide(feature)
        if explicit is not None:
            kind, method, override_key = explicit
            evidence = ClassificationEvidence(method, (), (), override_key)
        features.append(replace(feature, object_class=kind, classification=evidence))
    return features


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
    elif kind is ObjectClass.CONTOUR and geometry.geom_type in {"Polygon", "MultiPolygon"}:
        # Контур без смысла, даже залитый штриховкой: внутренность не объект, а область, чей
        # материал решают подписи; контур только разделяет покрытия.
        geometry = geometry.boundary
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
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ClassificationReport:
    source_sha256: str
    layer_map_fingerprint: str
    features: int
    unresolved_features: int
    groups: tuple[ClassificationGroup, ...]
    rules: tuple[RuleDescription, ...]
    unused_overrides: tuple[str, ...]
    labels: int = 0
    excluded_surface_labels: int = 0
    label_groups: tuple[LabelGroup, ...] = ()
    scope: str = (
        "Semantic assignments of imported geometry and label roles only. "
        "Name matches and explicit assignments "
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
    # С выводом незнакомого сеть неизвестного типа решена: у неё наибольший отступ сетей.
    unresolved_classes = (
        {ObjectClass.UNKNOWN}
        if params is None or params.infer_unknown
        else {ObjectClass.UNKNOWN, ObjectClass.UTILITY_UNKNOWN}
    )
    for feature in scene.features:
        evidence = feature.classification or ClassificationEvidence("unmatched")
        if feature.object_class in unresolved_classes:
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
    label_refs = {name_key(str(label.ref)) for label in scene.labels}
    unused += tuple(
        f"label_roles:{key}"
        for key in getattr(params, "label_roles", {})
        if name_key(key) not in label_refs
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
                i,
                r.pattern.pattern,
                r.target,
                r.geometry,
                r.object_class,
                r.priority,
                r.confirmed,
                r.reason,
            )
            for i, r in enumerate(layer_map.rules)
        ),
        unused_overrides=unused,
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
