"""Объяснения по шаблонам: только из трассы правил, без генерации текста моделью."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from green.domain.norms import DistanceRule
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Explanation, Plan, Verdict

if TYPE_CHECKING:
    from green.domain.norms import RuleBook
    from green.domain.planting import Placement, Rejection, RuleCheck

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
    ObjectClass.BUILDING: "наружной стены здания",
    ObjectClass.STRUCTURE: "сооружения",
    ObjectClass.EXISTING_TREE: "существующего дерева",
    ObjectClass.EXISTING_SHRUB: "существующего кустарника",
}

VERDICT_LABELS: dict[Verdict, str] = {
    Verdict.ALLOWED: "посадка допускается",
    Verdict.NEEDS_APPROVAL: "посадка требует согласования",
    Verdict.FORBIDDEN: "посадка запрещена",
    Verdict.UNKNOWN: "решение невозможно: нет данных",
}


def explain(plan: Plan, rulebook: RuleBook) -> Plan:
    explanations = [_placement(p, rulebook) for p in plan.placements]
    explanations += [_rejection(r, rulebook) for r in plan.rejections]
    return replace(plan, explanations=tuple(explanations))


def cite(check: RuleCheck, rulebook: RuleBook) -> str:
    rule = rulebook.rule(check.rule_id)
    if rule is None:
        return f"{check.rule_id} (правило отсутствует в базе)"
    act = rulebook.act_of(rule.citation)
    act_title = act.title if act is not None else rule.citation.act_id
    status = "" if rule.citation.is_verified else ", цитата не сверена"
    return f"{check.rule_id}: {act_title}, {rule.citation.clause}{status}"


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
    measure = ""
    if isinstance(rule, DistanceRule) and rule.measure_to.value == "outer_wall":
        measure = " до наружной стенки"
    return (
        f"до {target}{measure} {check.measured_m:.2f} м {sign} {check.threshold_m:.2f} м "
        f"({cite(check, rulebook)})"
    )


def _placement(placement: Placement, rulebook: RuleBook) -> Explanation:
    measured = [c for c in placement.checks if c.measured_m is not None]
    closest = sorted(measured, key=lambda c: (c.measured_m or 0) - (c.threshold_m or 0))[:4]
    no_data = [c for c in placement.checks if c.outcome is CheckOutcome.NO_DATA][:1]
    parts = [describe_check(c, rulebook) for c in (*closest, *no_data)]
    text = (
        f"Посадка №{placement.number}, {placement.species.name_ru} ({placement.species.name_lat}): "
        f"{VERDICT_LABELS[placement.verdict]}. Ближайшие ограничения: " + "; ".join(parts) + "."
    )
    return Explanation(placement.placement_id, placement.number, "placement", text)


def _rejection(rejection: Rejection, rulebook: RuleBook) -> Explanation:
    parts = [describe_check(c, rulebook) for c in rejection.blocking]
    text = (
        f"Отказ №{rejection.number}: {VERDICT_LABELS[rejection.verdict]}. Причины: "
        + "; ".join(parts)
        + "."
    )
    return Explanation(rejection.rejection_id, rejection.number, "rejection", text)
