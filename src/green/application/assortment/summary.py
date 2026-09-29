"""Сводка состава: доли по видам, родам и семействам, разнообразие и сезонность.

В сводке рядом с тем, что получилось, стоит то, что отсеяно и по какому основанию:
отчёт, показывающий только назначенные виды, не отличает «все остальные не подошли» от
«остальные вообще не рассматривались».
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from green.application.assortment.assign import Assignment
from green.application.validation import composition_issues
from green.domain.norms import PlantingType
from green.domain.planting import AssortmentSummary

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from green.application.params import PlanParams
    from green.domain.planting import Placement, Plan, Species

_MONTHS = range(1, 13)


def refresh_summaries(plan: Plan, params: PlanParams, catalog: Sequence[Species]) -> Plan:
    """Update current composition after editing, without reassigning chosen species.

    Solver diagnostics describe the original assignment. Their counts are kept
    explicitly as history, while shares, decorative months and quotas are fresh.
    """
    mixed = params.planting_type is PlantingType.TREE
    primary = tuple(p for p in plan.placements if p.species.is_tree) if mixed else plan.placements
    shrubs = tuple(p for p in plan.placements if p.species.is_shrub) if mixed else ()
    main = _refresh_summary(primary, plan.assortment_summary, params, catalog)
    secondary = (
        _refresh_summary(shrubs, plan.shrub_assortment_summary, params, catalog)
        if mixed and (shrubs or plan.shrub_assortment_summary is not None)
        else None
    )
    return replace(plan, assortment_summary=main, shrub_assortment_summary=secondary)


def _refresh_summary(
    placements: Sequence[Placement],
    old: AssortmentSummary | None,
    params: PlanParams,
    catalog: Sequence[Species],
) -> AssortmentSummary:
    existing = old.existing if old else {}
    index = {s.code: s for s in catalog} | {p.species.code: p.species for p in placements}
    issues = composition_issues(placements, params, tuple(index.values()), existing)
    assignment = Assignment(
        species_by_placement={p.placement_id: p.species.code for p in placements},
        solver="manual",
        quota_violations=tuple(issue.message for issue in issues),
        notes=(
            (
                "Состав, доли, сезонность и ограничения пересчитаны после ручной правки. "
                "Число мест без вида и причины отсева описывают исходный подбор."
            ),
        ),
    )
    return build_summary(
        assignment,
        index,
        existing,
        mode=params.assortment_mode,
        no_species=old.no_species if old else 0,
        rejected_by_kind=old.rejected_by_kind if old else {},
        rejected_by_rule=old.rejected_by_rule if old else {},
    )


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
    forms: set[str] = set()
    for code, count in counts.items():
        species = catalog.get(code)
        if species is None:
            continue
        forms.add("tree" if species.is_tree else "shrub")
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
        # Чьи месяцы в decor_by_month - по видам сводки, а не по типу плана: сводка деревьев
        # смешанного плана и сводка плана кустарников подписаны каждая своим.
        decor_of="mixed" if len(forms) > 1 else next(iter(forms), ""),
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
