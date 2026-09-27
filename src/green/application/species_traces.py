"""Трасса норм посадки - по виду, который на ней стоит.

Места выбираются до подбора вида: индекс ограничений размещения знает только вид профиля. После
подбора у посадки другой вид, у вида свои правила: колючий кустарник у пешеходного пути, отступ
от здания для широкой кроны, отступы по роду у теплотрасс. Независимая проверка плана меряет по
правилам вида, и объяснение обязано ссылаться на те же правила, иначе «посадка - норма - пункт»
расходится с тем, что проверено. Вердикт посадки здесь не меняется: его подтвердила проверка.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import TYPE_CHECKING

import shapely

from green.application.barriers import barrier_distance
from green.application.constraints import ConstraintIndex
from green.application.params import species_distance_rules

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.application.params import PlanParams
    from green.domain.norms import PlantingType, RuleBook
    from green.domain.objects import Feature
    from green.domain.planting import Plan


def with_species_traces(
    plan: Plan, features: Sequence[Feature], rulebook: RuleBook, params: PlanParams
) -> Plan:
    """План, где проверки каждой посадки измерены правилами её вида."""
    groups: dict[tuple[str, PlantingType], list[int]] = defaultdict(list)
    for i, placement in enumerate(plan.placements):
        groups[placement.species.code, placement.planting_type].append(i)
    placements = list(plan.placements)
    for (_, kind), members in groups.items():
        species = placements[members[0]].species
        local = replace(params, planting_type=kind)
        index = ConstraintIndex(
            features,
            species_distance_rules(rulebook, local, species),
            require_utility_data=params.require_utility_data,
            require_soil=False,
            require_work_boundary=False,
            planting_radius_m=local.footprint_radius_m,
            barrier_distance_m=barrier_distance(species.height_m) if params.root_barriers else None,
        )
        points = shapely.points([(placements[i].x, placements[i].y) for i in members])
        batch = index.evaluate(points)
        for row, i in enumerate(members):
            placements[i] = replace(placements[i], checks=batch.checks(row))
    return replace(plan, placements=tuple(placements))
