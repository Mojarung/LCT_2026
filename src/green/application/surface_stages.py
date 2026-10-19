"""Resolve existing/projected cover evidence without changing physical constraints."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import shapely

from green.application.approximation import inner_area, outer_area
from green.application.errors import InputError
from green.application.semantic_names import local_name, name_key
from green.domain.objects import ClassificationEvidence, ObjectClass

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from green.domain.objects import Feature, SourceRef, TextLabel

_SOURCE_KEY = re.compile(r"^[0-9a-f]{8}(?::[0-9a-f]{8})?$")
_PROPOSED = re.compile(r"(?:^|_)дв_(?:гп_п_|пп_(?:до_)?тип\d)")
_EXISTING = re.compile(r"(?:^|[|$_\s])(?:сущ|существующие|существующий|топо)(?:$|[_\s])")
_STAGES = frozenset({"existing", "proposed", "unknown"})
_UNRESOLVED_CONTEXT = re.compile(
    r"\b(?:не|нет|без|за|вместо|на месте)\b|\b(?:демонт|уничтож|снос)|"
    r"\b(?:not|demolition|remove|removed|instead)\b"
)


@dataclass(frozen=True, slots=True)
class StageLabelChange:
    ref: str
    text: str
    layer: str
    existing_material: str
    proposed_material: str
    polygon_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SurfaceStageReport:
    target: str
    proposed_polygons: tuple[str, ...] = ()
    superseded_labels: tuple[StageLabelChange, ...] = ()
    skipped_polygons: tuple[str, ...] = ()


def validate_source_stages(values: Mapping[str, str]) -> None:
    for key, stage in values.items():
        if not _SOURCE_KEY.fullmatch(key) or stage not in _STAGES:
            raise InputError(
                "surface_source_stages: ожидается file_sha8[:xref_hash8] "
                "и existing, proposed или unknown"
            )


def source_stage(ref: SourceRef, layer: str, stages: Mapping[str, str]) -> str:
    """Specific declarations win; Новый_ alone carries no stage evidence."""
    for key in (f"{ref.file_sha8}:{ref.xref_hash8}", ref.file_sha8):
        if key in stages:
            return stages[key]
    name = name_key(layer)
    proposed, existing = bool(_PROPOSED.search(local_name(name))), bool(_EXISTING.search(name))
    if proposed and existing:
        return "unknown"
    return "proposed" if proposed else "existing" if existing else "unknown"


def projected_label_view(
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    stages: Mapping[str, str],
    material_of: Callable[[TextLabel], int | None],
    is_functional: Callable[[TextLabel], bool],
) -> tuple[tuple[TextLabel, ...], SurfaceStageReport]:
    """Supersede only opposite, pre-work labels in certain projected polygon interiors."""
    validate_source_stages(stages)
    polygons, skipped = [], []
    for feature in features:
        if feature.geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            continue
        if not (feature.object_class is ObjectClass.LAWN or feature.object_class.is_hard_surface):
            continue
        if source_stage(feature.ref, feature.layer, stages) != "proposed":
            continue
        method = feature.classification.method if feature.classification else ""
        if (
            any(
                _UNRESOLVED_CONTEXT.search(re.sub(r"[_\-]+", " ", name_key(name)))
                for name in (local_name(feature.layer), feature.block or "")
            )
            or method.startswith(("assumed_", "symbol_assumed", "conflict", "unmatched"))
            or feature.uncertainty_footprint is not None
        ):
            skipped.append(str(feature.ref))
            continue
        polygons.append(feature)
    soil = [f for f in polygons if f.object_class is ObjectClass.LAWN]
    paved = [f for f in polygons if f.object_class is not ObjectClass.LAWN]
    # Same-stage polygon overlaps cannot silence contradictory evidence.
    soil_area = shapely.union_all([inner_area(f) for f in soil]).difference(
        shapely.union_all([outer_area(f) for f in paved])
    )
    paved_area = shapely.union_all([inner_area(f) for f in paved]).difference(
        shapely.union_all([outer_area(f) for f in soil])
    )
    shapely.prepare(soil_area)
    shapely.prepare(paved_area)
    changed, result = [], []
    for label in labels:
        material = material_of(label)
        evidence = label.surface_evidence
        if (
            material not in (1, 2)
            or is_functional(label)
            or source_stage(label.ref, label.layer, stages) != "existing"
            or (evidence is not None and evidence.method == "explicit_label")
        ):
            result.append(label)
            continue
        point = shapely.Point(label.x, label.y)
        area, owners, target = (
            (soil_area, soil, "soil") if material == 1 else (paved_area, paved, "paved")
        )
        if not area.contains(point):
            result.append(label)
            continue
        refs = tuple(str(f.ref) for f in owners if inner_area(f).contains(point))
        changed.append(
            StageLabelChange(
                str(label.ref),
                label.text,
                label.layer,
                "paved" if material == 1 else "soil",
                target,
                refs,
            )
        )
        result.append(
            replace(
                label,
                surface_role="ignore",
                surface_evidence=ClassificationEvidence("superseded_surface_stage"),
            )
        )
    return tuple(result), SurfaceStageReport(
        "proposed", tuple(str(f.ref) for f in polygons), tuple(changed), tuple(skipped)
    )
