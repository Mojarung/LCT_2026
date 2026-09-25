"""Объяснения по шаблонам: только из трассы правил, без генерации текста моделью."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from green.application.barriers import FAR_M, LOW_CROWN_M, NEAR_M, barrier_height_limit
from green.domain.norms import DistanceRule
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Explanation, Plan, Verdict

if TYPE_CHECKING:
    from green.domain.norms import AnyRule, RuleBook
    from green.domain.planting import Placement, Reason, Rejection, RuleCheck
    from green.domain.quality import PlantingValue

OBJECT_LABELS: dict[ObjectClass, str] = {
    ObjectClass.UTILITY_WATER: "водопровода",
    ObjectClass.UTILITY_SEWER: "канализации",
    ObjectClass.UTILITY_STORM: "водостока",
    ObjectClass.UTILITY_DRAIN: "дренажа",
    ObjectClass.UTILITY_HEAT: "теплосети",
    ObjectClass.UTILITY_GAS: "газопровода",
    ObjectClass.UTILITY_POWER: "силового кабеля",
    ObjectClass.UTILITY_TELECOM: "кабеля связи",
    ObjectClass.UTILITY_UNKNOWN: "сети неизвестного типа",
    ObjectClass.UTILITY_ACCESS: "смотрового колодца",
    ObjectClass.POWER_LINE_OVERHEAD: "воздушной линии",
    ObjectClass.POLE: "опоры освещения или контактной сети",
    ObjectClass.CURB: "бортового камня",
    ObjectClass.PAVEMENT_EDGE: "границы покрытия",
    ObjectClass.FENCE: "ограды",
    ObjectClass.ROAD: "края проезжей части",
    ObjectClass.SIDEWALK: "края тротуара",
    ObjectClass.TRAM: "трамвайных путей",
    ObjectClass.RAILWAY: "железнодорожных путей",
    ObjectClass.BUILDING: "наружной стены здания",
    ObjectClass.STRUCTURE: "сооружения",
    ObjectClass.SLOPE: "откоса",
    ObjectClass.EXISTING_TREE: "существующего дерева",
    ObjectClass.EXISTING_SHRUB: "существующего кустарника",
    ObjectClass.EXISTING_WOODLAND: "существующего древесного массива",
    ObjectClass.OBSTACLE: "наземного препятствия",
}

_FACTOR_LABELS = {
    "site": "условия места",
    "function": "роль в композиции",
    "decor": "декоративность",
    "longevity": "долговечность",
    "care": "простота ухода",
    "pilot": "применение в пилоте",
    "category": "рекомендация МГСН для категории",
}

_STRUCTURE_LABELS = {
    "row": "рядовая посадка одного вида",
    "group": "массив одного вида",
    "single": "одиночная посадка",
}

VERDICT_LABELS: dict[Verdict, str] = {
    Verdict.ALLOWED: "посадка допускается",
    Verdict.NEEDS_APPROVAL: "посадка требует согласования",
    Verdict.FORBIDDEN: "посадка запрещена",
    Verdict.UNKNOWN: "решение невозможно: нет данных",
}


def explain(plan: Plan, rulebook: RuleBook) -> Plan:
    values = plan.quality.values if plan.quality is not None else {}
    explanations = [_placement(p, rulebook, values.get(p.placement_id)) for p in plan.placements]
    explanations += [_rejection(r, rulebook) for r in plan.rejections]
    return replace(plan, explanations=tuple(explanations))


def citation_text(rule: AnyRule, rulebook: RuleBook) -> str:
    """«СП 42.13330.2016, п. 9.6, табл. 9.1: ...; 743-ПП, п. 3.6.3, табл. 3.6.1; ...»."""
    citation = rule.citation
    parts = [f"{rulebook.label_of(citation.act_id)}, {citation.clause}"]
    parts += [f"{rulebook.label_of(ref.act_id)}, {ref.clause}" for ref in citation.related]
    status = "" if citation.is_verified else " (цитата не сверена)"
    return "; ".join(parts) + status


def cite(check: RuleCheck, rulebook: RuleBook) -> str:
    rule = rulebook.rule(check.rule_id)
    if rule is None:
        return f"{check.rule_id} (правило отсутствует в базе)"
    return f"{check.rule_id}: {citation_text(rule, rulebook)}"


def describe_check(check: RuleCheck, rulebook: RuleBook) -> str:
    rule = rulebook.rule(check.rule_id)
    target = (
        OBJECT_LABELS.get(check.object_class, str(check.object_class)) if check.object_class else ""
    )
    if check.outcome is CheckOutcome.NO_DATA:
        return (
            f"сети в чертеже отсутствуют, отступ до {target} не проверен ({cite(check, rulebook)})"
        )
    if check.measured_m is None:
        return f"{target} в чертеже нет ({cite(check, rulebook)})"
    sign = ">=" if check.outcome is CheckOutcome.PASS else "<"
    barrier = ", допустимо с прикорневым барьером" if check.outcome is CheckOutcome.BARRIER else ""
    measure = ""
    if isinstance(rule, DistanceRule) and rule.measure_to.value == "outer_wall":
        measure = " до наружной стенки"
    return (
        f"до {target}{measure} {check.measured_m:.2f} м {sign} {check.threshold_m:.2f} м"
        f"{barrier} ({cite(check, rulebook)})"
    )


def _placement(
    placement: Placement, rulebook: RuleBook, value: PlantingValue | None = None
) -> Explanation:
    measured = [c for c in placement.checks if c.measured_m is not None]
    closest = sorted(measured, key=lambda c: (c.measured_m or 0) - (c.threshold_m or 0))[:4]
    no_data = [c for c in placement.checks if c.outcome is CheckOutcome.NO_DATA][:1]
    parts = [describe_check(c, rulebook) for c in (*closest, *no_data)]
    how = f", {', '.join(placement.notes)}" if placement.notes else ""
    text = (
        f"Посадка №{placement.number}, {placement.species.name_ru} "
        f"({placement.species.name_lat}){how}: {VERDICT_LABELS[placement.verdict]}. "
        "Ближайшие ограничения: " + "; ".join(parts) + "."
    )
    text += describe_assortment(placement)
    text += describe_value(value)
    return Explanation(placement.placement_id, placement.number, "placement", text)


# Вклад одной посадки - десятитысячные доли индекса, поэтому он показывается в тысячных
# (промилле): «+0,82 ‰» читается, «+0,0008» - нет. Меньше половины сотой промилле - ноль.
PERMILLE_ZERO = 0.005


def permille(delta: float) -> str:
    """Вклад в индекс в тысячных долях: «+0,82 ‰»."""
    value = delta * 1000
    return f"{'+' if value >= 0 else '−'}{abs(value):.2f} ‰".replace(".", ",")


def describe_value(value: PlantingValue | None) -> str:
    """Чем ценна посадка: вклад в индекс качества и главные причины из уже посчитанного."""
    if value is None:
        return ""
    why = f": {'; '.join(value.reasons)}" if value.reasons else ""
    weak = f" Слабее всего: {'; '.join(value.weak)}." if value.weak else ""
    if abs(value.delta * 1000) < PERMILLE_ZERO:
        return f" Ценность: вклад в индекс качества около нуля{why}.{weak}"
    if value.flagged:
        # Не «без неё план лучше»: посадка даёт зелень, но тянет вниз средний запас или
        # пригодность. Это слабое место, которое чинится сдвигом или заменой вида.
        gives = f" Что даёт: {'; '.join(value.reasons)}." if value.reasons else ""
        what = "; ".join(value.weak) or "ниже среднего по плану"
        # Отрицательный вклад - ещё не разрешение убрать посадку: оговорка проверки квот.
        scope = f" {value.scope}" if value.delta < 0 and value.scope else ""
        return f" Слабое место ({permille(value.delta)} к индексу качества): {what}.{gives}{scope}"
    if value.delta < 0:
        higher = permille(-value.delta)[1:]
        return (
            f" Ценность: без этой посадки расчётный индекс выше на {higher}{why}. {value.scope}"
            f"{weak}"
        )
    rank = f", больше, чем у {value.percentile:.0%} посадок плана" if value.percentile else ""
    return f" Ценность: вклад в индекс качества {permille(value.delta)}{rank}{why}.{weak}"


def describe_assortment(placement: Placement) -> str:
    """Почему именно этот вид: основания с ссылками и уступившие альтернативы."""
    info = placement.assortment
    if info is None:
        return ""
    alternatives = ""
    if info.alternatives:
        listed = ", ".join(f"{a.name_ru} {a.percent}%" for a in info.alternatives)
        alternatives = f" Альтернативы: {listed}."
    if info.status == "no_species":
        why = "; ".join(reason.text for reason in info.reasons)
        return f" Вид не подобран: {why}; оставлен вид профиля.{alternatives}"
    where = _STRUCTURE_LABELS.get(info.structure_kind or "", "")
    place = f", {where}" if where else ""
    grounds = [_reason(reason) for reason in info.reasons]
    if info.factors:
        # Процент должен быть проверяемым: рядом с ним стоят факторы, из которых он сложен.
        parts = ", ".join(
            f"{_FACTOR_LABELS.get(name, name)} {round(100 * value)}"
            for name, value in info.factors.items()
        )
        grounds.append(f"оценка по факторам из 100 ({parts})")
    said = f": {'; '.join(grounds)}" if grounds else ""
    return f" Вид: {placement.species.name_ru} ({info.percent}%{place}){said}.{alternatives}"


def _reason(reason: Reason) -> str:
    if reason.kind == "norm" and reason.rule_id:
        condition = f", условие: {reason.condition}" if reason.condition else ""
        return f"{reason.text} ({reason.rule_id}: {reason.source}){condition}"
    if reason.source:
        return f"{reason.text} ({reason.source})"
    return reason.text


def _rejection(rejection: Rejection, rulebook: RuleBook) -> Explanation:
    if rejection.note:
        state = (
            "место допустимо по нормам, посадка не выполнена"
            if rejection.verdict is Verdict.ALLOWED
            else VERDICT_LABELS[rejection.verdict]
        )
        text = f"Отказ №{rejection.number}: {state}. Причина: {rejection.note}."
        if rejection.blocking:
            text += (
                " Проверки: "
                + "; ".join(describe_check(check, rulebook) for check in rejection.blocking)
                + "."
            )
        return Explanation(rejection.rejection_id, rejection.number, "rejection", text)
    parts = [describe_check(c, rulebook) for c in rejection.blocking]
    text = (
        f"Отказ №{rejection.number}: {VERDICT_LABELS[rejection.verdict]}. Причины: "
        + "; ".join(parts)
        + "."
    )
    text += describe_barrier(rejection)
    return Explanation(rejection.rejection_id, rejection.number, "rejection", text)


def describe_barrier(rejection: Rejection) -> str:
    """Место, которое спас бы прикорневой барьер: при каком условии и для каких деревьев."""
    if rejection.barrier_m is None:
        return ""
    height = barrier_height_limit(rejection.barrier_m)
    allowed = NEAR_M if height <= LOW_CROWN_M else FAR_M
    return (
        f" С прикорневым барьером место допустимо для деревьев высотой до {height:.0f} м "
        f"(СП 42.13330.2016, табл. 9.1, прим. 5): до сети или бордюра "
        f"{_metres(rejection.barrier_m)} м, с барьером можно от {_metres(allowed)} м. "
        "Условие не выполнено: барьер в этом прогоне не заложен, включается параметром "
        "root_barriers."
    )


def _metres(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")
