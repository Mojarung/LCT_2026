"""Группы кустарников на местах деревьев, которые квоты разнообразия оставили пустыми.

Место в отказах с причиной-квотой (Rejection.note) допустимо по нормам для дерева, но ни
один вид деревьев в квоты 10-20-30 не укладывается. Такое место становится центром группы
кустарников: точки группы проверяются нормами для кустарника, виды назначаются тем же
подбором с теми же жёсткими квотами, но среди кустарников и отдельно от деревьев. Если в
группе посажен хотя бы один кустарник, отказ дерева на этом месте снимается. Разбор -
docs/notes/14-shrub-groups.md.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

import shapely

from green.application.assortment import GIVEN, SINGLE, assign_species
from green.domain.norms import PlantingType
from green.domain.planting import SHRUB_FORMS, Plan

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from green.application.params import PlanParams
    from green.application.placement import PlacementStrategy
    from green.application.surfaces import SurfaceMap
    from green.domain.norms import RuleBook
    from green.domain.objects import Feature, TextLabel
    from green.domain.planting import Placement, Rejection, Species


def fill_shrub_groups(  # noqa: PLR0913 - сценарий передаёт всё, что знает о прогоне
    plan: Plan,
    *,
    strategy: PlacementStrategy,
    features: Sequence[Feature],
    labels: Sequence[TextLabel],
    rulebook: RuleBook,
    catalog: Sequence[Species],
    params: PlanParams,
    existing: Mapping[str, int] | None = None,
    surface: SurfaceMap | None = None,
) -> Plan:
    empty = [r for r in plan.rejections if r.note]
    if (
        not params.shrub_groups
        or params.planting_type is not PlantingType.TREE
        or params.assortment_mode in {GIVEN, SINGLE}
        or not empty
    ):
        return plan
    shrubs = sorted((s for s in catalog if s.life_form in SHRUB_FORMS), key=lambda s: s.code)
    if not shrubs:
        return plan
    shrub_params = replace(
        params,
        planting_type=PlantingType.SHRUB,
        spacing_m=params.shrub_group_spacing_m,
        structure_patch_size=params.shrub_group_size**2,
        quota_species=params.shrub_quota_species,
        quota_genus=params.shrub_quota_genus,
        quota_family=params.shrub_quota_family,
        conifer_share=params.shrub_conifer_share,
    )
    points = strategy.shrub_groups(
        features,
        labels,
        rulebook,
        shrubs[0],  # вид-заглушка: подбор заменит его или место останется пустым
        shrub_params,
        centers=[(r.x, r.y) for r in empty],
        surface=surface,
    )
    if plan.placements and points:
        trees = shapely.STRtree(shapely.points([(p.x, p.y) for p in plan.placements]))
        hits = trees.query(
            shapely.points([(p.x, p.y) for p in points]),
            predicate="dwithin",
            distance=params.planting_radius_m + params.shrub_planting_radius_m - 1e-3,
        )
        blocked = set(hits[0].tolist())
        points = tuple(p for i, p in enumerate(points) if i not in blocked)
    assigned = assign_species(
        Plan(placements=points, rejections=()),
        rulebook,
        catalog,
        shrub_params,
        existing if params.shrub_quotas_use_inventory else None,
    )
    planted = assigned.placements
    reach = params.shrub_group_spacing_m * params.shrub_group_size
    filled = {r.rejection_id for r in empty if _near(r, planted, reach)}
    trees = plan.placements
    shrubs_numbered = tuple(
        replace(p, number=len(trees) + position) for position, p in enumerate(planted, 1)
    )
    summary = (
        f"Группы кустарников: заняты {len(filled)} из {len(empty)} мест, пустых из-за квот "
        f"деревьев; посажено {len(planted)} кустарников из {len(points)} точек, прошедших нормы."
    )
    return replace(
        plan,
        placements=(*trees, *shrubs_numbered),
        rejections=tuple(r for r in plan.rejections if r.rejection_id not in filled),
        warnings=(
            *plan.warnings,
            summary,
            *(f"Кустарники: {warning}" for warning in assigned.warnings),
        ),
        shrub_assortment_summary=assigned.assortment_summary,
    )


def _near(rejection: Rejection, planted: Sequence[Placement], reach: float) -> bool:
    return any(math.hypot(p.x - rejection.x, p.y - rejection.y) <= reach for p in planted)
