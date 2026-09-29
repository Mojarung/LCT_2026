"""Объяснения по шаблонам: только из трассы правил, без генерации текста моделью."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from green.application.barriers import FAR_M, LOW_CROWN_M, NEAR_M, barrier_height_limit
from green.domain.norms import DistanceRule, LawnKind
from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome, Explanation, Plan, Verdict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.domain.norms import AnyRule, RuleBook
    from green.domain.planting import Lawn, Placement, Reason, Rejection, RuleCheck
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
    ObjectClass.ZONE_POWER: "охранной зоны воздушной линии",
    ObjectClass.ZONE_GAS: "охранной зоны газопровода",
}

_FACTOR_LABELS = {
    "site": "условия места",
    "function": "роль в композиции",
    "decor": "декоративность",
    "longevity": "долговечность",
    "care": "простота ухода",
    "pilot": "применение в пилоте",
    "category": "рекомендация МГСН для категории",
    "shade": "тень взрослой кроны",
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

LAWN_LABELS: dict[LawnKind, str] = {
    LawnKind.KEPT: "сохраняемый или восстанавливаемый",
    LawnKind.NEW: "устраиваемый",
}


def explain(plan: Plan, rulebook: RuleBook) -> Plan:
    values = plan.quality.values if plan.quality is not None else {}
    explanations = [_placement(p, rulebook, values.get(p.placement_id)) for p in plan.placements]
    explanations += [_rejection(r, rulebook) for r in plan.rejections]
    explanations += [_lawn(lawn, rulebook) for lawn in plan.lawns]
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


# Прирост за крону шире 5 м (params.species_distance_rules, validation._threshold) идёт только
# к правилам табл. 9.1 СП 42.13330 (прим. 1 к ней): порог их проверки больше нормы таблицы на
# прирост. Разница меньше полусантиметра - округление, а не прирост.
CROWN_TABLE = "табл. 9.1"
CROWN_BASE_M = 5.0
_INCREMENT_EPS_M = 0.005
CROWN_NOTE = (
    " Прирост за крону - по прим. 1 к табл. 9.1 СП 42.13330.2016; его величину акт не задаёт"
)


def crown_increment_m(check: RuleCheck, rule: AnyRule | None) -> float:
    """Прирост порога проверки за крону шире 5 м: порог минус норма табл. 9.1; 0 - прироста нет."""
    if not isinstance(rule, DistanceRule) or check.threshold_m is None:
        return 0.0
    if CROWN_TABLE not in rule.citation.clause:
        return 0.0
    extra = check.threshold_m - rule.min_distance_m
    return extra if extra >= _INCREMENT_EPS_M else 0.0


def crown_note(checks: Sequence[RuleCheck], rulebook: RuleBook, crown_m: float | None) -> str:
    """Одна фраза на объяснение, если у проверок есть прирост за крону: основание и то, что его
    величина - толкование проекта. Ставка прироста выводится из порога и кроны вида, а не из
    параметров: объяснение говорит о том, что проверено."""
    extras = [e for c in checks if (e := crown_increment_m(c, rulebook.rule(c.rule_id)))]
    if not extras:
        return ""
    what = "прирост"
    if crown_m is not None and crown_m > CROWN_BASE_M:
        rate = round(extras[0] / (crown_m - CROWN_BASE_M), 2)
        what = f"{_number(rate)} м на метр кроны сверх {_number(CROWN_BASE_M)} м"
    return f"{CROWN_NOTE}, {what} - толкование проекта (crown_extra_per_m)."


def describe_check(check: RuleCheck, rulebook: RuleBook, crown_m: float | None = None) -> str:
    """Проверка словами. crown_m - взрослая крона вида: с ней прирост порога назван кроной."""
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
    sign = "≥" if check.outcome is CheckOutcome.PASS else "<"
    barrier = ", допустимо с прикорневым барьером" if check.outcome is CheckOutcome.BARRIER else ""
    measure = ""
    if isinstance(rule, DistanceRule) and rule.measure_to.value == "outer_wall":
        measure = " до наружной стенки"
    norm = ""
    if check.threshold_m is not None:
        norm = f" {sign} {_metres(check.threshold_m)} м"
        if extra := crown_increment_m(check, rule):
            crown = (
                f"{_number(crown_m)} м"
                if crown_m is not None and crown_m > CROWN_BASE_M
                else f"шире {_number(CROWN_BASE_M)} м"
            )
            norm += (
                f": {_metres(check.threshold_m - extra)} м по {CROWN_TABLE} и "
                f"{_metres(extra)} м за крону {crown}"
            )
    return (
        f"до {target}{measure} {_metres(check.measured_m)} м{norm}"
        f"{barrier} ({cite(check, rulebook)})"
    )


def _placement(
    placement: Placement, rulebook: RuleBook, value: PlantingValue | None = None
) -> Explanation:
    measured = [c for c in placement.checks if c.measured_m is not None]
    closest = sorted(measured, key=lambda c: (c.measured_m or 0) - (c.threshold_m or 0))[:4]
    no_data = [c for c in placement.checks if c.outcome is CheckOutcome.NO_DATA][:1]
    crown_m = placement.species.crown_mature_m
    shown = (*closest, *no_data)
    parts = [describe_check(c, rulebook, crown_m) for c in shown]
    how = f", {', '.join(placement.notes)}" if placement.notes else ""
    text = (
        f"Посадка №{placement.number}, {placement.species.name_ru} "
        f"({placement.species.name_lat}){how}: {VERDICT_LABELS[placement.verdict]}. "
        "Ближайшие ограничения: " + "; ".join(parts) + "."
    )
    text += crown_note(shown, rulebook, crown_m)
    text += describe_assortment(placement)
    text += describe_value(value)
    return Explanation(placement.placement_id, placement.number, "placement", text)


# Вклад одной посадки - десятитысячные доли индекса 0-1. Дендрологу он показывается пунктами
# шкалы 0-100 (сотыми индекса): «0,089 пункта из 100» читается без знания промилле. Точность
# прежняя - сотая промилле, то есть тысячная пункта; ноль - меньше половины сотой промилле.
PERMILLE_ZERO = 0.005


def index_points(delta: float) -> str:
    """Величина вклада в индекс без знака, в пунктах из 100: «0,089 пункта из 100»."""
    # «0,09», а не «0,090»; точность - тысячная пункта.
    text = f"{abs(delta) * 100:.3f}".removesuffix("0")
    return f"{text.replace('.', ',')} пункта из 100"


def _index_change(delta: float) -> str:
    verb = "повышает" if delta >= 0 else "снижает"
    return f"{verb} индекс качества плана на {index_points(delta)}"


def describe_value(value: PlantingValue | None) -> str:
    """Чем ценна посадка: вклад в индекс качества и главные причины из уже посчитанного."""
    if value is None:
        return ""
    why = f": {'; '.join(value.reasons)}" if value.reasons else ""
    weak = f" Слабее всего: {'; '.join(value.weak)}." if value.weak else ""
    if abs(value.delta * 1000) < PERMILLE_ZERO:
        return (
            " Ценность: вклад в индекс качества около нуля - цели участка по её показателям уже "
            f"выполнены{why}.{weak}"
        )
    if value.flagged:
        # Не «без неё план лучше»: посадка даёт зелень, но тянет вниз средний запас или
        # пригодность. Это слабое место, которое чинится сдвигом или заменой вида.
        gives = f" Что даёт: {'; '.join(value.reasons)}." if value.reasons else ""
        what = "; ".join(value.weak) or "ниже среднего по плану"
        # Отрицательный вклад - ещё не разрешение убрать посадку: оговорка проверки квот.
        scope = f" {value.scope}" if value.delta < 0 and value.scope else ""
        return f" Слабое место ({_index_change(value.delta)}): {what}.{gives}{scope}"
    if value.delta < 0:
        return (
            " Ценность: без этой посадки расчётный индекс выше на "
            f"{index_points(value.delta)}{why}. {value.scope}{weak}"
        )
    rank = f", больше, чем у {value.percentile:.0%} посадок плана" if value.percentile else ""
    return f" Ценность: {_index_change(value.delta)}{rank}{why}.{weak}"


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
            text += crown_note(rejection.blocking, rulebook, None)
        return Explanation(rejection.rejection_id, rejection.number, "rejection", text)
    parts = [describe_check(c, rulebook) for c in rejection.blocking]
    text = (
        f"Отказ №{rejection.number}: {VERDICT_LABELS[rejection.verdict]}. Причины: "
        + "; ".join(parts)
        + "."
    )
    # Вид у отказа не выбран: прирост назван без кроны и без ставки.
    text += crown_note(rejection.blocking, rulebook, None)
    text += describe_barrier(rejection)
    return Explanation(rejection.rejection_id, rejection.number, "rejection", text)


def _lawn(lawn: Lawn, rulebook: RuleBook) -> Explanation:
    """Газон: вид, площадь, что вырезано и основания - только правила участка из свода."""
    grounds = []
    for rule_id in lawn.rule_ids:
        rule = rulebook.rule(rule_id)
        grounds.append(
            f"{rule_id}: {citation_text(rule, rulebook)}"
            if rule is not None
            else f"{rule_id} (правило отсутствует в базе)"
        )
    how = "".join(f"; {note}" for note in lawn.notes)
    area = f"{lawn.area_m2:,.1f}".replace(",", " ").replace(".", ",")
    text = (
        f"Газон №{lawn.number}: {LAWN_LABELS[lawn.kind]}, {area} м²{how}. "
        f"Основания: {'; '.join(grounds)}."
    )
    return Explanation(lawn.lawn_id, lawn.number, "lawn", text)


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


def _number(value: float) -> str:
    """Число без лишних нулей: «6», «6,5», «0,5»."""
    return f"{value:g}".replace(".", ",")
