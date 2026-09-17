"""Подбор ассортимента: какой вид поставить в уже выбранную точку и почему именно его.

Проход выполняется после размещения: позиции и измеренные расстояния до объектов уже
есть в Placement.checks, поэтому видозависимые нормы (369-ПП, 743-ПП п. 3.6.18, отступы по
роду, крона более 5 м, высота под ВЛ) проверяются без повторной геометрии.

Порядок: структуры (ряды, группы, одиночки) -> контекст точки -> жёсткие фильтры ->
оценка пригодности -> назначение видов с квотами разнообразия -> сводка.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from green.application.assortment.assign import Assignment, Candidate, assign
from green.application.assortment.context import site_context
from green.application.assortment.filters import COMPOSITION, SpeciesVerdict, species_verdict
from green.application.assortment.scoring import Score, percent, score_species
from green.application.assortment.structures import build_structures
from green.application.assortment.summary import build_summary
from green.application.barriers import BARRIER_CONDITION
from green.domain.norms import PlantingType
from green.domain.planting import (
    SHRUB_FORMS,
    TREE_FORMS,
    Alternative,
    AssortmentInfo,
    Reason,
    Rejection,
    Species,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from green.application.assortment.context import SiteContext
    from green.application.params import PlanParams
    from green.domain.norms import RuleBook
    from green.domain.planting import Placement, Plan

ASSIGNED = "assigned"
GIVEN = "given"
SINGLE = "single"
NO_SPECIES = "no_species"
_ALTERNATIVES = 3
_SPLIT_REASON = Reason(
    COMPOSITION,
    "структура одним видом в квоты разнообразия не влезла: вид назначен этой посадке отдельно "
    "из оставшегося допуска",
)
_FORMS = {
    PlantingType.TREE: TREE_FORMS,
    PlantingType.SHRUB: SHRUB_FORMS,
    PlantingType.HEDGE: SHRUB_FORMS,
}


def assign_species(
    plan: Plan,
    rulebook: RuleBook,
    catalog: Sequence[Species],
    params: PlanParams,
    existing: Mapping[str, int] | None = None,
) -> Plan:
    """Назначить вид каждой посадке плана и собрать сводку состава."""
    index = {species.code: species for species in catalog}
    # Квоты деревьев считаются по существующим деревьям, квоты кустарников - по кустарникам:
    # доля вида в популяции улицы имеет смысл внутри одной жизненной формы.
    forms = _FORMS.get(params.planting_type, frozenset())
    existing = {
        code: count
        for code, count in (existing or {}).items()
        if code in index and index[code].life_form in forms
    }
    if params.assortment_mode == SINGLE or not plan.placements:
        return _single_mode(plan, catalog, params, existing, index)

    structures = build_structures(plan.placements, params.spacing_m, params.structure_patch_size)
    structure_of = {
        placement_id: structure
        for structure in structures
        for placement_id in structure.placement_ids
    }
    usable = [s for s in catalog if s.life_form in _FORMS.get(params.planting_type, frozenset())]
    contexts: dict[str, SiteContext] = {}
    verdicts: dict[str, list[SpeciesVerdict]] = {}
    scores: dict[tuple[str, str], Score] = {}
    candidates: list[Candidate] = []
    rejected_kind = Counter[str]()
    rejected_rule = Counter[str]()

    for placement in plan.placements:
        structure = structure_of.get(placement.placement_id)
        ctx = site_context(
            placement,
            structure_id=structure.structure_id if structure else None,
            structure_kind=structure.kind if structure else None,
        )
        contexts[placement.placement_id] = ctx
        allowed: list[SpeciesVerdict] = []
        for species in usable:
            verdict = species_verdict(species, ctx, rulebook, params)
            if not verdict.allowed:
                blocking = verdict.blocking
                if blocking is not None:
                    rejected_kind[blocking.kind] += 1
                    if blocking.rule_id:
                        rejected_rule[blocking.rule_id] += 1
                continue
            allowed.append(verdict)
            score = score_species(species, ctx, params)
            scores[(placement.placement_id, species.code)] = score
            candidates.append(
                Candidate(
                    placement_id=placement.placement_id,
                    structure_id=structure.structure_id if structure else placement.placement_id,
                    structure_kind=structure.kind if structure else SINGLE,
                    species=species,
                    score=score.total,
                )
            )
        verdicts[placement.placement_id] = allowed

    assignment = assign(candidates, structures, index, existing, params)
    status = GIVEN if params.assortment_mode == GIVEN else ASSIGNED
    placements = tuple(
        _apply(
            placement,
            contexts,
            verdicts,
            scores,
            chosen=assignment.species_by_placement,
            index=index,
            status=status,
            split=assignment.split_placements,
        )
        for placement in plan.placements
    )
    placements, unplanted = _drop_unplanted(placements, plan.rejections)
    no_species = len(unplanted)
    summary = build_summary(
        assignment,
        index,
        existing,
        mode=params.assortment_mode,
        no_species=no_species,
        rejected_by_kind=dict(rejected_kind),
        rejected_by_rule=dict(rejected_rule),
    )
    warnings = (*plan.warnings, *_warnings(assignment, no_species), *_conditions(placements))
    return replace(
        plan,
        placements=placements,
        rejections=(*plan.rejections, *unplanted),
        assortment_summary=summary,
        warnings=tuple(warnings),
    )


def _drop_unplanted(
    placements: Sequence[Placement], rejections: Sequence[Rejection]
) -> tuple[tuple[Placement, ...], tuple[Rejection, ...]]:
    """Место без вида не попадает в план: в чертеже не должно быть посадки вида профиля,
    который здесь мог не пройти нормы или квоты. Место уходит в отказы со своей причиной."""
    planted = [p for p in placements if p.assortment is None or p.assortment.status != NO_SPECIES]
    next_number = max((r.number for r in rejections), default=0) + 1
    unplanted = tuple(
        Rejection(
            rejection_id=p.placement_id,
            number=next_number + offset,
            planting_type=p.planting_type,
            x=p.x,
            y=p.y,
            verdict=p.verdict,
            blocking=p.checks,  # все пройдены: место допустимо по нормам, мешают только квоты
            note="; ".join(r.text for r in p.assortment.reasons) if p.assortment else "",
        )
        for offset, p in enumerate(
            p for p in placements if p.assortment is not None and p.assortment.status == NO_SPECIES
        )
    )
    renumbered = tuple(replace(p, number=position) for position, p in enumerate(planted, 1))
    return renumbered, unplanted


def _warnings(assignment: Assignment, no_species: int) -> list[str]:
    messages = [f"Подбор ассортимента: {note}." for note in assignment.notes]
    if assignment.quota_violations:  # по построению пусто; если нет - это ошибка сервиса
        messages.append(
            "Подбор ассортимента: ОШИБКА, квоты разнообразия нарушены: "
            + "; ".join(assignment.quota_violations)
        )
    if no_species:
        messages.append(
            f"Подбор ассортимента: {no_species} мест допустимы по нормам, но не заняты: "
            "ни один допустимый вид не укладывается в квоты разнообразия, места перенесены "
            "в отказы."
        )
    return messages


def _conditions(placements: Sequence[Placement]) -> list[str]:
    """Условия актов, под которыми допущены назначенные виды: обязательства для проекта."""
    counts: Counter[tuple[str, str, str]] = Counter()
    with_barrier: dict[str, str] = {}
    for placement in placements:
        info = placement.assortment
        if info is None or info.status == NO_SPECIES:
            continue
        for reason in info.reasons:
            if reason.condition.startswith(BARRIER_CONDITION):
                # Барьер у каждой посадки свой (кабель, теплосеть, борт): в предупреждениях одна
                # строка, подробности в объяснении посадки и на слое GREEN_TREES_BARRIER.
                with_barrier[placement.placement_id] = reason.rule_id
            elif reason.condition:
                counts[(placement.species.name_ru, reason.condition, reason.rule_id)] += 1
    messages = [
        f"Условие допуска: {name}, {count} посадок - {condition} ({rule_id})."
        for (name, condition, rule_id), count in sorted(counts.items())
    ]
    if with_barrier:
        rule_id = next(iter(with_barrier.values()))
        messages.append(
            f"Условие допуска: {len(with_barrier)} деревьев стоят ближе табличной нормы к сетям "
            f"или борту и допустимы только с прикорневым барьером ({rule_id})."
        )
    return messages


def _apply(  # noqa: PLR0913 - все части решения нужны, чтобы собрать карточку посадки
    placement: Placement,
    contexts: Mapping[str, SiteContext],
    verdicts: Mapping[str, list[SpeciesVerdict]],
    scores: Mapping[tuple[str, str], Score],
    *,
    chosen: Mapping[str, str],
    index: Mapping[str, Species],
    status: str,
    split: frozenset[str] = frozenset(),
) -> Placement:
    ctx = contexts[placement.placement_id]
    allowed = verdicts.get(placement.placement_id, [])
    code = chosen.get(placement.placement_id)
    if code is None or code not in index:
        return replace(
            placement,
            assortment=AssortmentInfo(
                status=NO_SPECIES,
                percent=0,
                factors={},
                structure_id=ctx.structure_id,
                structure_kind=ctx.structure_kind,
                reasons=(_no_species_reason(allowed, given=status == GIVEN),),
                alternatives=_alternatives(placement.placement_id, allowed, scores, None, None),
            ),
        )
    score = scores[(placement.placement_id, code)]
    verdict = next(v for v in allowed if v.species.code == code)
    return replace(
        placement,
        species=index[code],
        assortment=AssortmentInfo(
            status=status,
            percent=percent(score),
            factors=score.factors,
            structure_id=ctx.structure_id,
            structure_kind=ctx.structure_kind,
            reasons=(
                (*verdict.reasons, _SPLIT_REASON)
                if placement.placement_id in split
                else verdict.reasons
            ),
            alternatives=_alternatives(placement.placement_id, allowed, scores, code, score.total),
        ),
    )


def _no_species_reason(allowed: Sequence[SpeciesVerdict], *, given: bool) -> Reason:
    if allowed and given:
        return Reason(COMPOSITION, "заданные количества видов исчерпаны")
    if allowed:
        return Reason(
            COMPOSITION,
            f"ни один из {len(allowed)} допустимых по нормам видов не укладывается в квоты "
            "разнообразия 10-20-30 (с учётом существующих деревьев)",
        )
    return Reason(COMPOSITION, "ни один вид каталога не прошёл ограничения этой точки")


def _alternatives(
    placement_id: str,
    allowed: Sequence[SpeciesVerdict],
    scores: Mapping[tuple[str, str], Score],
    chosen_code: str | None,
    chosen_score: float | None,
) -> tuple[Alternative, ...]:
    """Три лучших вида, кроме выбранного: данные для ручной правки в будущем редакторе."""
    ranked = sorted(
        (
            (scores[(placement_id, v.species.code)].total, v.species)
            for v in allowed
            if v.species.code != chosen_code and (placement_id, v.species.code) in scores
        ),
        key=lambda item: (-item[0], item[1].code),
    )
    return tuple(
        Alternative(
            code=species.code,
            name_ru=species.name_ru,
            percent=round(100 * total),
            why_not=(
                "оценка ниже"
                if chosen_score is None or total <= chosen_score
                else "уступил однородности структуры или квоте разнообразия"
            ),
        )
        for total, species in ranked[:_ALTERNATIVES]
    )


def _single_mode(
    plan: Plan,
    catalog: Sequence[Species],
    params: PlanParams,
    existing: Mapping[str, int],
    index: Mapping[str, Species],
) -> Plan:
    """Режим «один вид на прогон»: вид не меняется, но оценка и структура считаются."""
    structures = build_structures(plan.placements, params.spacing_m, params.structure_patch_size)
    structure_of = {
        placement_id: structure
        for structure in structures
        for placement_id in structure.placement_ids
    }
    placements = []
    for placement in plan.placements:
        structure = structure_of.get(placement.placement_id)
        ctx = site_context(
            placement,
            structure_id=structure.structure_id if structure else None,
            structure_kind=structure.kind if structure else None,
        )
        score = score_species(placement.species, ctx, params)
        placements.append(
            replace(
                placement,
                assortment=AssortmentInfo(
                    status=SINGLE,
                    percent=percent(score),
                    factors=score.factors,
                    structure_id=ctx.structure_id,
                    structure_kind=ctx.structure_kind,
                ),
            )
        )
    assignment = Assignment(
        species_by_placement={p.placement_id: p.species.code for p in placements},
        solver=SINGLE,
    )
    summary = build_summary(
        assignment,
        index or {s.code: s for s in catalog},
        existing,
        mode=params.assortment_mode,
        no_species=0,
        rejected_by_kind={},
        rejected_by_rule={},
    )
    return replace(plan, placements=tuple(placements), assortment_summary=summary)
