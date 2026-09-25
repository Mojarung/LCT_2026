"""Прикорневые барьеры: на сколько норма табл. 9.1 сокращается для дерева данной высоты.

СП 42.13330.2016, табл. 9.1, прим. 5: при устройстве защитных прикорневых барьеров дерево
может высаживаться от инженерных сетей и бордюров улиц и дорог не ближе 0,5 м при высоте
кроны менее 5 м и не ближе 1 м при высоте кроны от 5 до 20 м. Для более высокой кроны
сокращения нет. Высоты кроны в каталоге нет, вместо неё берётся высота дерева: она не меньше
высоты кроны, поэтому замена только ужесточает условие.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from green.domain.norms import DistanceRule, PlantingType, Severity
from green.domain.planting import CheckOutcome, Verdict

if TYPE_CHECKING:
    from green.domain.norms import RuleBook
    from green.domain.planting import Plan, Rejection

LOW_CROWN_M = 5.0
HIGH_CROWN_M = 20.0
NEAR_M = 0.5
FAR_M = 1.0
BARRIER_NOTE = "посадка с прикорневым барьером"
BARRIER_CONDITION = "прикорневой барьер"
_EPS_M = 1e-3  # тот же допуск, что у проверки норм: ровно на расстоянии - не нарушение


def barrier_distance(height_m: float) -> float | None:
    """Наименьшее расстояние до сети или бордюра с барьером; None - сокращение не положено."""
    if height_m < LOW_CROWN_M:
        return NEAR_M
    if height_m <= HIGH_CROWN_M:
        return FAR_M
    return None


def barrier_option(rejection: Rejection, rulebook: RuleBook) -> float | None:
    """Место, которое спас бы прикорневой барьер: ближайшее расстояние до сети или бордюра.

    Барьер снимает только нормы до инженерных сетей и бордюров (прим. 5 к табл. 9.1) и не ближе
    NEAR_M. Если место закрывает хоть одна другая жёсткая норма (здание, колодец, опора) или
    сеть ближе NEAR_M, барьер не поможет - None. Место, пустое из-за квот, в расчёт не идёт.
    """
    if rejection.note or rejection.verdict is not Verdict.FORBIDDEN:
        return None
    closest: float | None = None
    for check in rejection.blocking:
        if check.outcome is not CheckOutcome.FAIL:
            continue
        rule = rulebook.rule(check.rule_id)
        if not isinstance(rule, DistanceRule) or rule.severity is not Severity.FORBID:
            continue
        relaxable = (
            rule.planting_type is PlantingType.TREE
            and rule.object_class.is_barrier_relaxable
            and check.measured_m is not None
            and check.measured_m >= NEAR_M - _EPS_M
        )
        if not relaxable or check.measured_m is None:
            return None
        closest = check.measured_m if closest is None else min(closest, check.measured_m)
    return closest


def mark_barrier_options(plan: Plan, rulebook: RuleBook, *, applied: bool) -> Plan:
    """Отметить отказы, которые снял бы барьер. Если барьеры уже в прогоне, отмечать нечего."""
    if applied:
        return plan
    rejections = tuple(replace(r, barrier_m=barrier_option(r, rulebook)) for r in plan.rejections)
    count = sum(1 for r in rejections if r.barrier_m is not None)
    return replace(plan, rejections=rejections, stats={**plan.stats, "barrier_places": count})


def barrier_height_limit(distance_m: float) -> float:
    """До какой высоты дерева барьер разрешает место: ближе FAR_M - только ниже 5 м."""
    return LOW_CROWN_M if distance_m < FAR_M - _EPS_M else HIGH_CROWN_M
