"""Keep label provenance; annotations and work descriptions cannot prove soil."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from shapely.geometry import Point

from green.application.errors import InputError
from green.application.semantic_names import material_context_requires_review, name_key
from green.domain.objects import ClassificationEvidence, Feature, ObjectClass

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from green.application.classification import LayerMap
    from green.domain.objects import TextLabel


def classify_labels(
    labels: Sequence[TextLabel], layer_map: LayerMap, overrides: Mapping[str, str]
) -> tuple[TextLabel, ...]:
    explicit: dict[str, tuple[str, str]] = {}
    for ref, role in overrides.items():
        key = name_key(ref)
        if not key or key in explicit or role not in {"soil", "paved", "ignore"}:
            raise InputError(f"label_roles: неверное или повторное назначение {ref!r}: {role!r}")
        explicit[key] = (ref, role)
    result = []
    cache = {}
    for label in labels:
        chain = label.block_chain or ((label.block,) if label.block else ())
        key = (label.layer, chain)
        if key not in cache:
            cache[key] = _automatic_role(label, layer_map, chain)
        role, evidence = cache[key]
        if entry := explicit.get(name_key(str(label.ref))):
            ref, role = entry
            evidence = ClassificationEvidence("explicit_label", evidence.matched_rules, (), ref)
        result.append(replace(label, surface_role=role, surface_evidence=evidence))
    return tuple(result)


def _automatic_role(
    label: TextLabel, layer_map: LayerMap, chain: tuple[str, ...]
) -> tuple[str, ClassificationEvidence]:
    feature = Feature(label.ref, label.layer, Point(label.x, label.y), label.block)
    kind, evidence = layer_map.decide(feature)
    for ancestor in reversed(chain):
        parent_kind, parent_evidence = layer_map.decide(replace(feature, block=ancestor))
        if parent_kind is ObjectClass.IGNORE:
            kind, evidence = parent_kind, parent_evidence
            break
    if kind is ObjectClass.IGNORE:
        return "ignore", replace(evidence, method="annotation_label")
    if material_context_requires_review(label.layer, *chain):
        return "ignore", replace(evidence, method="material_context")
    return ("ignore" if evidence.method == "conflict" else "auto"), evidence


@dataclass(frozen=True, slots=True)
class LabelGroup:
    layer: str
    block: str | None
    surface_role: str
    evidence: ClassificationEvidence
    block_chain: tuple[str, ...]
    labels: int
    source_refs: tuple[str, ...]


def label_report_groups(labels: Sequence[TextLabel]) -> tuple[LabelGroup, ...]:
    groups: dict[
        tuple[str, str | None, str, ClassificationEvidence, tuple[str, ...]], list[str]
    ] = defaultdict(list)
    for label in labels:
        groups[
            (
                label.layer,
                label.block,
                label.surface_role,
                label.surface_evidence or ClassificationEvidence("unmatched"),
                label.block_chain,
            )
        ].append(str(label.ref))
    return tuple(LabelGroup(*key, len(refs), tuple(refs[:5])) for key, refs in groups.items())
