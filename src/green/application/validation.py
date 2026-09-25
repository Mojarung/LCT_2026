"""Final-plan certificate within declared input geometry and configured rules.

Distance checks do not trust Placement.checks or ConstraintIndex.evaluate. They
query every object capable of violating the threshold and measure it directly.
Recognition, completeness of survey data, and global optimality are separate
claims. Surface interpretation and rule applicability are shared domain policy.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely

from green.application.barriers import BARRIER_CONDITION, BARRIER_NOTE, barrier_distance
from green.application.constraints import ConstraintIndex
from green.application.params import active_distance_rules
from green.application.species_norms import species_norms
from green.application.surfaces import build_surface_map
from green.domain.norms import MeasureTo, PlantingType, Severity
from green.domain.objects import ObjectClass
from green.domain.planting import Verdict

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from numpy.typing import NDArray

    from green.application.params import PlanParams
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import DistanceRule, RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Placement, Plan, Species

EPS_M = 1e-3


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    placements: tuple[str, ...]
    message: str
    rule_id: str = ""
    measured_m: float | None = None
    required_m: float | None = None


@dataclass(frozen=True, slots=True)
class PlanValidation:
    checked_placements: int
    issues: tuple[ValidationIssue, ...]
    scope: str = (
        "Final coordinates, species, configured distances, footprints, "
        "pair spacing and composition limits"
    )
    assumptions: tuple[str, ...] = (
        "Input units, object classes, survey completeness and surface evidence must be correct",
        (
            "Surface and rule applicability policies are shared with generation; "
            "distance and composition checks are recomputed"
        ),
        "No certificate of physical soil quality, legal completeness, or global optimum",
        "Conifer lower share is a soft preference, not a hard feasibility constraint",
    )

    @property
    def ok(self) -> bool:
        return not self.issues


class _Objects:
    def __init__(self, features: Sequence[Feature]) -> None:
        self.tree = shapely.STRtree([f.geometry for f in features])
        self.radii = np.array([(f.diameter_m or 0.0) / 2 for f in features])
        self.errors = np.array([f.geometry_error_m for f in features], dtype=np.float64)
        if not np.isfinite(self.errors).all() or (self.errors < 0).any():
            raise ValueError("Unbounded or invalid input geometry error")

    def nearby_clearance(
        self, points: NDArray[np.object_], threshold: float, measure: MeasureTo
    ) -> NDArray[np.float64]:
        """Infinity means proven farther than threshold, not an absent observation."""
        radii = self.errors + (self.radii if measure is MeasureTo.OUTER_WALL else 0)
        result = np.full(len(points), np.inf)
        for start in range(0, len(points), 512):
            subset = points[start : start + 512]
            q, f = self.tree.query(
                subset, predicate="dwithin", distance=threshold + float(radii.max()) + EPS_M
            )
            values = np.maximum(0, shapely.distance(subset[q], self.tree.geometries[f]) - radii[f])
            np.minimum.at(result, start + q, values)
        return result


def _group_placements(
    placements: Sequence[Placement], params: PlanParams, issues: list[ValidationIssue]
) -> dict[tuple[str, PlantingType], list[Placement]]:
    groups: dict[tuple[str, PlantingType], list[Placement]] = defaultdict(list)
    ids = Counter(p.placement_id for p in placements)
    for identity, count in ids.items():
        if count > 1:
            issues.append(
                ValidationIssue("duplicate_id", (identity,), "Placement id is not unique")
            )
    for placement in placements:
        if not math.isfinite(placement.x) or not math.isfinite(placement.y):
            issues.append(
                ValidationIssue(
                    "nonfinite_coordinate", (placement.placement_id,), "Coordinate is not finite"
                )
            )
            continue
        groups[placement.species.code, placement.planting_type].append(placement)
        accepted = (
            {Verdict.ALLOWED, Verdict.NEEDS_APPROVAL}
            if params.allow_needs_approval
            else {Verdict.ALLOWED}
        )
        if placement.verdict not in accepted:
            issues.append(
                ValidationIssue(
                    "unaccepted_verdict", (placement.placement_id,), str(placement.verdict)
                )
            )
        if (placement.planting_type is PlantingType.TREE) != placement.species.is_tree:
            issues.append(
                ValidationIssue(
                    "life_form", (placement.placement_id,), "Species and planting type disagree"
                )
            )
    return groups


def validate_plan(  # noqa: PLR0913 - certificate has explicit input provenance
    plan: Plan,
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    rulebook: RuleBook,
    params: PlanParams,
    *,
    catalog: Sequence[Species] = (),
    existing: Mapping[str, int] | None = None,
    surface: SurfaceMap | None = None,
) -> PlanValidation:
    """Проверка плана заново от объектов чертежа: отступы, посадочные места, квоты.

    surface - карта покрытий прогона. Она функция чертежа и параметров покрытий, построенная
    той же build_surface_map, поэтому взять её у сценария - не довериться генератору: каждое
    расстояние, место и квоту проверка всё равно считает сама. None - построить здесь.
    """
    issues: list[ValidationIssue] = []
    groups = _group_placements(plan.placements, params, issues)
    by_class: dict[ObjectClass, list[Feature]] = defaultdict(list)
    for feature in features:
        by_class[feature.object_class].append(feature)
    objects = {cls: _Objects(items) for cls, items in by_class.items()}
    base_index = ConstraintIndex(features, [], require_utility_data=params.require_utility_data)
    if not params.require_soil:
        surface = None
    elif surface is None:
        surface = build_surface_map(
            features,
            labels,
            base_index.boundary,
            params.surface_cell_m,
            max_distance_m=params.surface_max_distance_m,
            ambiguity_m=params.surface_ambiguity_m,
            tree_distance_m=params.tree_seed_distance_m,
            inference_mode=params.surface_inference_mode,
        )
    for (_, kind), placements in groups.items():
        local = replace(params, planting_type=kind)
        species = placements[0].species
        points = shapely.points([(p.x, p.y) for p in placements])
        index = ConstraintIndex(
            features,
            [],
            require_utility_data=params.require_utility_data,
            surface=surface,
            require_soil=params.require_soil,
            require_work_boundary=params.require_work_boundary,
            planting_radius_m=local.footprint_radius_m,
        )
        issues.extend(
            ValidationIssue(
                "footprint",
                (placements[position].placement_id,),
                "Planting footprint lacks permitted ground or crosses boundary/obstacle",
            )
            for position in np.flatnonzero(~index.plantable(points))
        )
        if params.require_utility_data and not index.has_utility_data:
            issues.append(
                ValidationIssue(
                    "missing_utilities",
                    tuple(p.placement_id for p in placements),
                    "No recognised utility data",
                )
            )
        norms = species_norms(species, rulebook, params.territory, params.planting_category)
        if norms.blocking:
            issues.append(
                ValidationIssue(
                    "species_rule",
                    tuple(p.placement_id for p in placements),
                    norms.blocking.text,
                    norms.blocking.rule_id,
                )
            )
        _check_distances(placements, points, objects, rulebook, local, issues=issues)
        issues.extend(_site_conditions(placements, points, objects, local))
    finite = [p for group in groups.values() for p in group]
    issues.extend(_spacing(finite, params))
    issues.extend(composition_issues(plan.placements, params, catalog, existing or {}))
    return PlanValidation(len(plan.placements), tuple(issues))


def _check_distances(  # noqa: PLR0913 - validation context
    placements: Sequence[Placement],
    points: NDArray[np.object_],
    objects: Mapping[ObjectClass, _Objects],
    rulebook: RuleBook,
    params: PlanParams,
    *,
    issues: list[ValidationIssue],
) -> None:
    species = placements[0].species
    rules = active_distance_rules(
        rulebook, params, species.name_lat, species.crown_mature_m, species.traits
    )
    for rule in rules:
        nearby = objects.get(rule.object_class)
        if nearby is None:
            continue
        threshold = _threshold(rule, species, params)
        clearances = nearby.nearby_clearance(points, threshold, rule.measure_to)
        if (
            rule.object_class is ObjectClass.POWER_LINE_OVERHEAD
            and species.height_m > params.max_height_under_lines_m
        ):
            issues.extend(
                ValidationIssue(
                    "overhead_height",
                    (placements[int(i)].placement_id,),
                    "Species exceeds configured height under overhead lines",
                    rule.rule_id,
                )
                for i in np.flatnonzero(clearances + EPS_M < threshold)
            )
        for position in np.flatnonzero(clearances + EPS_M < threshold):
            placement = placements[int(position)]
            measured = float(clearances[position])
            if rule.severity is Severity.NEEDS_APPROVAL:
                if placement.verdict is Verdict.NEEDS_APPROVAL and params.allow_needs_approval:
                    continue
                code = "approval_not_marked"
            else:
                relaxed = (
                    barrier_distance(species.height_m)
                    if params.root_barriers
                    and rule.object_class.is_barrier_relaxable
                    and params.planting_type is PlantingType.TREE
                    else None
                )
                if relaxed is not None and measured + EPS_M >= relaxed:
                    if _barrier_documented(placement):
                        continue
                    code = "barrier_not_documented"
                else:
                    code = "distance"
            issues.append(
                ValidationIssue(
                    code,
                    (placement.placement_id,),
                    "Final species/coordinate does not meet the recorded condition",
                    rule.rule_id,
                    measured,
                    threshold,
                )
            )


def _threshold(rule: DistanceRule, species: Species, params: PlanParams) -> float:
    grows = (
        rule.severity is Severity.FORBID
        and "табл. 9.1" in rule.citation.clause
        and (
            not params.crown_extra_classes or rule.object_class.value in params.crown_extra_classes
        )
    )
    extra = max(0, species.crown_mature_m - 5) * params.crown_extra_per_m if grows else 0.0
    return rule.min_distance_m + extra


def _site_conditions(
    placements: Sequence[Placement],
    points: NDArray[np.object_],
    objects: Mapping[ObjectClass, _Objects],
    params: PlanParams,
) -> list[ValidationIssue]:
    species = placements[0].species
    issues = []
    if species.hardiness_zone > params.region_hardiness_zone:
        issues.append(
            ValidationIssue(
                "hardiness",
                tuple(p.placement_id for p in placements),
                "Species exceeds configured hardiness zone",
            )
        )
    if species.salt_tolerance == 0:
        affected = np.zeros(len(points), dtype=bool)
        for cls in (ObjectClass.ROAD, ObjectClass.CURB):
            nearby = objects.get(cls)
            if nearby is not None:
                affected |= (
                    nearby.nearby_clearance(points, params.salt_zone_m, MeasureTo.EDGE)
                    < params.salt_zone_m
                )
        issues.extend(
            ValidationIssue(
                "salt",
                (placements[int(i)].placement_id,),
                "Salt-intolerant species in configured salt strip",
            )
            for i in np.flatnonzero(affected)
        )
    return issues


def _barrier_documented(placement: Placement) -> bool:
    return BARRIER_NOTE in placement.notes or (
        placement.assortment is not None
        and any(
            reason.condition.startswith(BARRIER_CONDITION)
            for reason in placement.assortment.reasons
        )
    )


def _spacing(placements: Sequence[Placement], params: PlanParams) -> list[ValidationIssue]:
    if not placements:
        return []
    points = shapely.points([(p.x, p.y) for p in placements])
    tree = shapely.STRtree(points)
    radii = np.array(
        [replace(params, planting_type=p.planting_type).footprint_radius_m for p in placements]
    )
    steps = np.array(
        [
            (
                params.spacing_m
                if p.planting_type is params.planting_type
                else params.shrub_group_spacing_m
            )
            * 0.95
            for p in placements
        ]
    )
    maximum = max(float(steps.max()), float(radii.max()) * 2)
    issues = []
    for start in range(0, len(points), 128):
        left, right = tree.query(points[start : start + 128], predicate="dwithin", distance=maximum)
        left = left + start
        keep = left < right
        left, right = left[keep], right[keep]
        for i, j, distance in zip(
            left, right, shapely.distance(points[left], points[right]), strict=True
        ):
            same = placements[i].planting_type is placements[j].planting_type
            required = max(radii[i] + radii[j], steps[i] if same else 0.0)
            if distance + EPS_M < required:
                issues.append(
                    ValidationIssue(
                        "spacing",
                        (placements[i].placement_id, placements[j].placement_id),
                        "Planting footprints or required spacing overlap",
                        measured_m=float(distance),
                        required_m=float(required),
                    )
                )
    return issues


def composition_issues(
    placements: Sequence[Placement],
    params: PlanParams,
    catalog: Sequence[Species],
    existing: Mapping[str, int],
) -> list[ValidationIssue]:
    """Recompute non-geometric constraints from current plants and inventory."""
    if params.assortment_mode == "single":
        return []
    issues = []
    if params.assortment_mode == "given":
        for code, count in Counter(p.species.code for p in placements).items():
            if count > params.given_assortment.get(code, 0):
                issues.append(
                    ValidationIssue("given_count", (), f"{code}: {count} exceeds given assortment")
                )
        return issues
    species_by_code = {s.code: s for s in catalog} | {p.species.code: p.species for p in placements}
    for trees in (True, False):
        part = [p for p in placements if p.species.is_tree is trees]
        grown, shares = _quota_terms(trees, params, existing, species_by_code)
        issues.extend(
            ValidationIssue("quota", (), f"{attribute} {key}: {count} > {limit}")
            for attribute, key, count, limit in _quota_excess(part, grown, shares, species_by_code)
        )
    return issues


def trim_to_quotas(
    placements: Sequence[Placement],
    params: PlanParams,
    catalog: Sequence[Species],
    existing: Mapping[str, int],
    *,
    removable: Callable[[Placement], bool],
) -> tuple[Placement, ...]:
    """Снять добавочные посадки, пока состав не уложится в квоты разнообразия.

    Этапы, которые добирают кустарник к готовому плану (ряд у борта, подлесок, группы на
    газоне), подбирают вид каждый в своей выборке, а квота считается по всему плану. Здесь
    лишние снимаются с конца, только те, что removable разрешает: основу плана квоты уже
    прошли при подборе. Расчёт квот тот же, что у проверки (composition_issues).
    """
    if params.assortment_mode in {"single", "given"}:
        return tuple(placements)
    kept = list(placements)
    species_by_code = {s.code: s for s in catalog} | {p.species.code: p.species for p in kept}
    for trees in (True, False):
        grown, shares = _quota_terms(trees, params, existing, species_by_code)
        while True:
            part = [p for p in kept if p.species.is_tree is trees]
            excess = _quota_excess(part, grown, shares, species_by_code)
            if not excess:
                break
            attribute, key, _, _ = excess[0]
            victim = next(
                (
                    p
                    for p in reversed(part)
                    if removable(p) and getattr(p.species, attribute) == key
                ),
                None,
            )
            if victim is None:
                break
            kept.remove(victim)
    return tuple(kept)


def drop_spacing_conflicts(
    placements: Sequence[Placement],
    params: PlanParams,
    *,
    removable: Callable[[Placement], bool],
) -> tuple[Placement, ...]:
    """Снять добавочные посадки, чьи посадочные места налезают на соседей.

    Правило то же, что у проверки (_spacing): ямы не перекрываются, у посадок одного типа -
    ещё и шаг. Этапы кустарника держат его сами, но на стыке двух бортов или у соседних
    деревьев их выборки встречаются; из пары снимается более поздняя из разрешённых.
    """
    issues = _spacing(placements, params)
    if not issues:
        return tuple(placements)
    order = {p.placement_id: k for k, p in enumerate(placements)}
    dropped: set[int] = set()
    pairs = sorted(tuple(sorted(order[pid] for pid in issue.placements)) for issue in issues)
    for first, second in sorted(pairs, key=lambda pair: pair[1]):
        if first in dropped or second in dropped:
            continue
        if removable(placements[second]):
            dropped.add(second)
        elif removable(placements[first]):
            dropped.add(first)
    return tuple(p for k, p in enumerate(placements) if k not in dropped)


def _quota_terms(
    trees: bool,  # noqa: FBT001 - деревья или кустарники: две ветви одной формулы
    params: PlanParams,
    existing: Mapping[str, int],
    species_by_code: Mapping[str, Species],
) -> tuple[dict[str, int], tuple[float, ...]]:
    """Уже растущие растения, входящие в квоты, и доли квот для деревьев или кустарников."""
    grown = {
        code: count
        for code, count in existing.items()
        if code in species_by_code
        and species_by_code[code].is_tree is trees
        and (trees or params.shrub_quotas_use_inventory)
    }
    shares = (
        (params.quota_species, params.quota_genus, params.quota_family, params.conifer_share[1])
        if trees
        else (
            params.shrub_quota_species,
            params.shrub_quota_genus,
            params.shrub_quota_family,
            params.shrub_conifer_share[1],
        )
    )
    # A standalone shrub profile uses its primary quotas, like assignment.
    if not trees and params.planting_type is not PlantingType.TREE:
        shares = (
            params.quota_species,
            params.quota_genus,
            params.quota_family,
            params.conifer_share[1],
        )
    return grown, shares


def _quota_excess(
    part: Sequence[Placement],
    grown: Mapping[str, int],
    shares: tuple[float, ...],
    species_by_code: Mapping[str, Species],
) -> list[tuple[str, str | bool, int, int]]:
    """Превышения квот: признак (вид, род, семейство, хвойность), значение, число, предел."""
    excess: list[tuple[str, str | bool, int, int]] = []
    attributes = ("code", "genus", "family", "is_conifer")
    for attribute, share in zip(attributes, shares, strict=True):
        counts = Counter(getattr(p.species, attribute) for p in part)
        old: Counter[str | bool] = Counter()
        for code, count in grown.items():
            old[getattr(species_by_code[code], attribute)] += count
        for key, count in counts.items():
            if attribute == "is_conifer" and not key:
                continue
            limit = max(1, math.floor(share * len(part) + 1e-9))
            if attribute != "is_conifer" and grown:
                exhausted = old[key] > share * sum(grown.values()) + 1e-9
                limit = (
                    0
                    if exhausted
                    else min(
                        limit,
                        math.floor(share * (len(part) + sum(grown.values())) + 1e-9) - old[key],
                    )
                )
            if count > limit:
                excess.append((attribute, key, count, limit))
    return excess
