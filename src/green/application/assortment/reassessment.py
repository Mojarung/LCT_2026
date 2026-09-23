"""Reassess manually retained species without running the assignment solver."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import shapely

from green.application.assortment.context import site_context
from green.application.assortment.filters import species_verdict
from green.application.assortment.scoring import percent, score_species
from green.application.assortment.structures import build_structures
from green.application.barriers import BARRIER_NOTE
from green.application.errors import InputError
from green.domain.norms import PlantingType
from green.domain.planting import Alternative, AssortmentInfo, Reason, Verdict

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from green.application.constraints import ConstraintIndex
    from green.application.params import PlanParams
    from green.domain.norms import RuleBook
    from green.domain.planting import Placement, Species

NOT_ON_SOIL = "Точка вне грунта или вне границы работ: посадочное место здесь не рассматривается."


@dataclass(frozen=True, slots=True)
class _Choice:
    placement: Placement
    reasons: tuple[Reason, ...]


def reassess_placements(
    placements: Sequence[Placement],
    rulebook: RuleBook,
    catalog: Sequence[Species],
    params: PlanParams,
    index_for: Callable[[Species, PlantingType], ConstraintIndex],
) -> tuple[Placement, ...]:
    """Refresh current local evidence; alternatives still require a whole-plan check.

    Species-specific distances are measured for each alternative, not copied
    from the chosen species. Structure, suitability and conditions reflect the
    remaining coordinates. Quotas/spacing of substitutions are not promised.
    """
    groups: dict[PlantingType, list[Placement]] = defaultdict(list)
    for placement in placements:
        matches = (placement.planting_type is PlantingType.TREE and placement.species.is_tree) or (
            placement.planting_type in {PlantingType.SHRUB, PlantingType.HEDGE}
            and placement.species.is_shrub
        )
        if not matches:
            raise InputError("Вид растения не соответствует поддерживаемому типу посадки")
        groups[placement.planting_type].append(placement)
    refreshed: dict[str, Placement] = {}
    for kind, members in groups.items():
        local = replace(params, planting_type=kind)
        if kind is not params.planting_type and kind is not PlantingType.TREE:
            local = replace(
                local,
                spacing_m=params.shrub_group_spacing_m,
                structure_patch_size=params.shrub_group_size**2,
            )
        choices = _choices(members, catalog, rulebook, local, index_for)
        current = [choices[p.placement_id][p.species.code].placement for p in members]
        structures = build_structures(
            [p for p in current if p.verdict is not Verdict.FORBIDDEN],
            local.spacing_m,
            local.structure_patch_size,
        )
        structure_of = {identity: s for s in structures for identity in s.placement_ids}
        for placement in current:
            structure = structure_of.get(placement.placement_id)
            info = _info(
                choices[placement.placement_id][placement.species.code],
                choices[placement.placement_id].values(),
                local,
                structure.structure_id if structure else None,
                structure.kind if structure else None,
            )
            refreshed[placement.placement_id] = replace(placement, assortment=info)
    return tuple(refreshed[p.placement_id] for p in placements)


def _choices(
    placements: Sequence[Placement],
    catalog: Sequence[Species],
    rulebook: RuleBook,
    params: PlanParams,
    index_for: Callable[[Species, PlantingType], ConstraintIndex],
) -> dict[str, dict[str, _Choice]]:
    species_by_code = {s.code: s for s in catalog} | {p.species.code: p.species for p in placements}
    points = shapely.points([(p.x, p.y) for p in placements])
    result: dict[str, dict[str, _Choice]] = {p.placement_id: {} for p in placements}
    for species in species_by_code.values():
        matches = species.is_tree if params.planting_type is PlantingType.TREE else species.is_shrub
        if not matches:
            continue
        index = index_for(species, params.planting_type)
        batch, fits = index.evaluate(points), index.plantable(points)
        for i, placement in enumerate(placements):
            candidate = replace(placement, species=species, checks=batch.checks(i), assortment=None)
            verdict = species_verdict(species, site_context(candidate), rulebook, params)
            notes = tuple(n for n in placement.notes if n not in {NOT_ON_SOIL, BARRIER_NOTE})
            if not fits[i]:
                notes = (*notes, NOT_ON_SOIL)
            if verdict.blocking is not None:
                notes = (*notes, verdict.blocking.text)
            if batch.needs_barrier(i):
                notes = (*notes, BARRIER_NOTE)
            result[placement.placement_id][species.code] = _Choice(
                replace(
                    candidate,
                    verdict=batch.verdict(i) if fits[i] and verdict.allowed else Verdict.FORBIDDEN,
                    notes=tuple(dict.fromkeys(notes)),
                ),
                verdict.reasons,
            )
    return result


def _info(
    chosen: _Choice,
    choices: Iterable[_Choice],
    params: PlanParams,
    structure_id: str | None,
    structure_kind: str | None,
) -> AssortmentInfo:
    ctx = site_context(chosen.placement, structure_id, structure_kind)
    score = score_species(chosen.placement.species, ctx, params)
    accepted = (
        {Verdict.ALLOWED, Verdict.NEEDS_APPROVAL}
        if params.allow_needs_approval
        else {Verdict.ALLOWED}
    )
    ranked = sorted(
        (
            (
                score_species(
                    c.placement.species,
                    site_context(c.placement, structure_id, structure_kind),
                    params,
                ).total,
                c.placement.species,
            )
            for c in choices
            if c.placement.species.code != chosen.placement.species.code
            and c.placement.verdict in accepted
        ),
        key=lambda item: (-item[0], item[1].code),
    )
    return AssortmentInfo(
        status="manual",
        percent=percent(score) if chosen.placement.verdict is not Verdict.FORBIDDEN else 0,
        factors=score.factors,
        structure_id=structure_id,
        structure_kind=structure_kind,
        reasons=chosen.reasons,
        alternatives=tuple(
            Alternative(
                species.code,
                species.name_ru,
                round(100 * value),
                "Сохранён выбранный вид; замена требует проверки квот и расстояний до соседей.",
            )
            for value, species in ranked[:3]
        ),
    )
