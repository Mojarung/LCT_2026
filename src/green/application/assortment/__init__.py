"""Подбор ассортимента: какой вид поставить в уже выбранную точку и почему именно его.

Проход выполняется после размещения: позиции и измеренные расстояния до объектов уже
есть в Placement.checks, поэтому видозависимые нормы (369-ПП, 743-ПП п. 3.6.18, отступы по
роду, крона более 5 м, высота под ВЛ) проверяются без повторной геометрии.

Порядок: структуры (ряды, группы, одиночки) -> контекст точки -> жёсткие фильтры ->
оценка пригодности -> назначение видов с квотами разнообразия -> сводка.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from green.application.assortment.assign import Assignment, Candidate, assign
from green.application.assortment.context import site_context
from green.application.assortment.filters import COMPOSITION, SpeciesVerdict, species_verdict
from green.application.assortment.scoring import Score, percent, score_species
from green.application.assortment.spacing import crowded, enforce_spacing, tree_neighbors
from green.application.assortment.structures import GROUP, ROW, build_structures
from green.application.assortment.summary import build_summary
from green.application.barriers import BARRIER_CONDITION
from green.application.params import lawn_step_m
from green.application.wording import counted, plural
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
    """Keep solver tie-breaking independent of opaque public placement IDs.

    IDs derived from absolute coordinates change when a drawing is translated.
    Give the solver spatial ranks, then restore public IDs on both plants and
    new rejections. Rounding only orders locations; all geometry stays exact.
    """
    if params.assortment_mode == SINGLE or not plan.placements:
        return _assign_species(plan, rulebook, catalog, params, existing)
    ordered = sorted(
        plan.placements,
        key=lambda p: (round(p.x, 6), round(p.y, 6), p.placement_id),
    )
    forward = {p.placement_id: f"site-{i:012d}" for i, p in enumerate(ordered)}
    backward = {local: public for public, local in forward.items()}
    local = replace(
        plan,
        placements=tuple(replace(p, placement_id=forward[p.placement_id]) for p in plan.placements),
    )
    result = _assign_species(local, rulebook, catalog, params, existing)
    return replace(
        result,
        placements=tuple(
            replace(p, placement_id=backward[p.placement_id]) for p in result.placements
        ),
        rejections=(
            *plan.rejections,
            *(
                replace(r, rejection_id=backward[r.rejection_id])
                for r in result.rejections[len(plan.rejections) :]
            ),
        ),
    )


def _assign_species(
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

    structures = build_structures(plan.placements, lawn_step_m(params), params.structure_patch_size)
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
                    score=score.total - _obligation(verdict, species, params),
                )
            )
        verdicts[placement.placement_id] = allowed

    neighbors = tree_neighbors(plan.placements, params)
    assignment = assign(candidates, structures, index, existing, params, neighbors=neighbors)
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
            used_up=assignment.used_up,
            crowded=assignment.crowded,
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
    warnings = (
        *plan.warnings,
        *_warnings(assignment, no_species, soft=params.quota_penalty > 0),
        *conditions(placements),
    )
    return replace(
        plan,
        placements=placements,
        rejections=(*plan.rejections, *unplanted),
        assortment_summary=summary,
        warnings=tuple(warnings),
    )


def _obligation(verdict: SpeciesVerdict, species: Species, params: PlanParams) -> float:
    """Поправка к оценке за вид с условием посадки или слабый аллерген.

    Индекс качества вычитает штраф за каждую такую посадку (quality.PENALTIES): условие -
    обязательство на годы (барьер, мужские клоны, контроль вида группы III), слабый аллерген
    743-ПП не запрещает, но заказчику он не нужен. Подбор узнаёт об этом той же поправкой:
    при равных квотах берётся вид без условия.
    """
    penalty = params.condition_penalty
    if penalty <= 0:
        return 0.0
    conditional = any(reason.condition for reason in verdict.reasons)
    return penalty * (int(conditional) + int(species.allergen == 1))


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


def _warnings(assignment: Assignment, no_species: int, *, soft: bool) -> list[str]:
    messages = [f"Подбор ассортимента: {note}." for note in assignment.notes]
    if assignment.quota_violations and soft:
        # Мягкие квоты (quota_penalty > 0): доля сверх квоты - штраф подбора, а не нарушение;
        # место, прошедшее нормы, не пустеет (docs/notes/34: в принятых проектах главная
        # порода - до 73%). Потолок хвойных и здесь жёсткий.
        messages.append(
            "Подбор ассортимента: доля вида выше квоты разнообразия (квота мягкая, перебор - "
            "штраф подбора, место не пустеет): " + "; ".join(assignment.quota_violations)
        )
    elif assignment.quota_violations:  # по построению пусто; если нет - это ошибка сервиса
        messages.append(
            "Подбор ассортимента: ОШИБКА, квоты разнообразия нарушены: "
            + "; ".join(assignment.quota_violations)
        )
    if no_species:
        places = counted(no_species, "место допустимо", "места допустимы", "мест допустимы")
        taken = plural(no_species, "не занято", "не заняты", "не заняты")
        moved = plural(no_species, "место перенесено", "места перенесены", "места перенесены")
        messages.append(
            f"Подбор ассортимента: {places} по нормам, но {taken}: ни один допустимый вид не "
            f"укладывается в квоты разнообразия, {moved} в отказы."
        )
    return messages


def conditions(placements: Sequence[Placement]) -> list[str]:
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
                with_barrier[placement.placement_id] = _act(reason)
            elif reason.condition:
                counts[(placement.species.name_ru, reason.condition, _act(reason))] += 1
    messages = [
        f"Условие допуска: {name}, {counted(count, 'посадка', 'посадки', 'посадок')} - "
        f"{condition} ({act})."
        for (name, condition, act), count in sorted(counts.items())
    ]
    if with_barrier:
        act = next(iter(with_barrier.values()))
        messages.append(
            f"Условие допуска: {len(with_barrier)} деревьев стоят ближе табличной нормы к сетям "
            f"или борту и допустимы только с прикорневым барьером ({act})."
        )
    return messages


def _act(reason: Reason) -> str:
    """Акты и пункты основания без пересказа пунктов: «369-ПП, приложение 1, п. 3.12;
    369-ПП, приложение 2, пп. 5.1-5.3».

    rule_id человеку ничего не говорит (жюри по дизайну, итерация 7); он остаётся в объяснении
    посадки. Нет цитаты - остаётся rule_id, чтобы основание не пропало.
    """
    heads = [part.split(":")[0].strip() for part in reason.source.split(";")]
    return "; ".join(dict.fromkeys(h for h in heads if h)) or reason.rule_id


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
    used_up: Mapping[str, str] | None = None,
    crowded: Mapping[str, Mapping[str, str]] | None = None,
) -> Placement:
    ctx = contexts[placement.placement_id]
    near = (crowded or {}).get(placement.placement_id, {})
    lost = _Lost(used_up or {}, ctx.structure_kind, near)
    allowed = verdicts.get(placement.placement_id, [])
    code = chosen.get(placement.placement_id)
    if code is None or code not in index:
        reason = _no_species_reason(allowed, given=status == GIVEN)
        if allowed and all(v.species.code in near for v in allowed):
            best = max(
                allowed,
                key=lambda v: (
                    scores[(placement.placement_id, v.species.code)].total,
                    v.species.code,
                ),
            )
            reason = Reason(COMPOSITION, f"место оставлено пустым: {near[best.species.code]}")
        return replace(
            placement,
            assortment=AssortmentInfo(
                status=NO_SPECIES,
                percent=0,
                factors={},
                structure_id=ctx.structure_id,
                structure_kind=ctx.structure_kind,
                reasons=(reason,),
                alternatives=_alternatives(placement.placement_id, allowed, scores, None, lost),
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
            alternatives=_alternatives(
                placement.placement_id, allowed, scores, (code, score.total), lost
            ),
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


@dataclass(frozen=True, slots=True)
class _Lost:
    """Чему уступил вид с оценкой выше выбранного: квоте (какой) или однородности структуры."""

    used_up: Mapping[str, str]
    structure_kind: str | None
    crowded: Mapping[str, str] = field(default_factory=dict)  # вид -> тесно рядом с соседом

    def why(self, code: str) -> str:
        if code in self.crowded:
            return self.crowded[code]
        if code in self.used_up:
            return self.used_up[code]
        if self.structure_kind == ROW:
            return "ряд сажается одним видом"
        if self.structure_kind == GROUP:
            return "группа сажается одним видом"
        return "квоты разнообразия по улице"


def _alternatives(
    placement_id: str,
    allowed: Sequence[SpeciesVerdict],
    scores: Mapping[tuple[str, str], Score],
    chosen: tuple[str, float] | None,
    lost: _Lost,
) -> tuple[Alternative, ...]:
    """Три лучших вида, кроме выбранного: данные для ручной правки в будущем редакторе."""
    chosen_code, chosen_score = chosen or (None, None)
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
                else lost.why(species.code)
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
    structures = build_structures(plan.placements, lawn_step_m(params), params.structure_patch_size)
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
    placements = _thin_single(placements, params)
    placements, unplanted = _drop_unplanted(placements, plan.rejections)
    assignment = Assignment(
        species_by_placement={p.placement_id: p.species.code for p in placements},
        solver=SINGLE,
    )
    summary = build_summary(
        assignment,
        index or {s.code: s for s in catalog},
        existing,
        mode=params.assortment_mode,
        no_species=len(unplanted),
        rejected_by_kind={},
        rejected_by_rule={},
    )
    return replace(
        plan,
        placements=placements,
        rejections=(*plan.rejections, *unplanted),
        assortment_summary=summary,
    )


def _thin_single(placements: Sequence[Placement], params: PlanParams) -> list[Placement]:
    """Один вид на прогон: вид не выбрать, поэтому из тесной по кронам пары место снимается."""
    neighbors = tree_neighbors(placements, params)
    if neighbors is None or not neighbors.pairs:
        return list(placements)
    by_id = {p.placement_id: p for p in placements}
    species = {p.species.code: p.species for p in placements}
    scores = {
        (p.placement_id, p.species.code): p.assortment.percent if p.assortment else 0
        for p in placements
    }
    chosen = {p.placement_id: p.species.code for p in placements}
    kept = enforce_spacing(chosen, neighbors, species, scores)
    reasons = crowded(
        kept, {pid: [chosen[pid]] for pid in chosen if pid not in kept}, neighbors, species
    )
    result = []
    for pid, placement in by_id.items():
        if pid in kept or placement.assortment is None:
            result.append(placement)
            continue
        text = next(iter(reasons.get(pid, {}).values()), "шаг по взрослым кронам")
        result.append(
            replace(
                placement,
                assortment=replace(
                    placement.assortment,
                    status=NO_SPECIES,
                    reasons=(Reason(COMPOSITION, f"место оставлено пустым: {text}"),),
                ),
            )
        )
    return result
