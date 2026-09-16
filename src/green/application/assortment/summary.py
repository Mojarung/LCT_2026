"""Сводка состава: доли по видам, родам и семействам, разнообразие и сезонность.

В сводке рядом с тем, что получилось, стоит то, что отсеяно и по какому основанию:
отчёт, показывающий только назначенные виды, не отличает «все остальные не подошли» от
«остальные вообще не рассматривались».
"""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

from green.domain.planting import AssortmentSummary

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from green.application.assortment.assign import Assignment
    from green.domain.planting import Species

_MONTHS = range(1, 13)


def build_summary(  # noqa: PLR0913 - сводка собирается из всех итогов прохода сразу
    assignment: Assignment,
    catalog: Mapping[str, Species],
    existing: Mapping[str, int],
    *,
    mode: str,
    no_species: int,
    rejected_by_kind: Mapping[str, int],
    rejected_by_rule: Mapping[str, int],
) -> AssortmentSummary:
    counts = Counter(assignment.species_by_placement.values())
    total = sum(counts.values())
    genus = Counter[str]()
    family = Counter[str]()
    conifers = 0
    months = dict.fromkeys(_MONTHS, 0)
    for code, count in counts.items():
        species = catalog.get(code)
        if species is None:
            continue
        genus[species.genus] += count
        family[species.family] += count
        conifers += count if species.is_conifer else 0
        for month in species.decor_months:
            months[month] += count
    return AssortmentSummary(
        mode=mode,
        solver=assignment.solver,
        counts=dict(sorted(counts.items())),
        genus_shares=_shares(genus, total),
        family_shares=_shares(family, total),
        conifer_share=conifers / total if total else 0.0,
        shannon=_shannon(counts.values(), total),
        decor_by_month=months,
        no_species=no_species,
        quota_violations=assignment.quota_violations,
        existing=dict(sorted(existing.items())),
        rejected_by_kind=dict(sorted(rejected_by_kind.items())),
        rejected_by_rule=dict(sorted(rejected_by_rule.items(), key=lambda kv: (-kv[1], kv[0]))),
        notes=assignment.notes,
    )


def _shares(counter: Mapping[str, int], total: int) -> dict[str, float]:
    if not total:
        return {}
    return {key: round(value / total, 4) for key, value in sorted(counter.items())}


def _shannon(counts: Iterable[int], total: int) -> float:
    """Индекс Шеннона: 0 - монокультура, растёт с числом и равномерностью видов."""
    if total <= 0:
        return 0.0
    return round(-sum((v / total) * math.log(v / total) for v in counts if v > 0), 4)
