"""Что известно о месте посадки: расстояния по классам объектов и принадлежность структуре."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from green.domain.objects import ObjectClass
from green.domain.planting import CheckOutcome

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from green.domain.planting import Placement


@dataclass(frozen=True, slots=True)
class SiteContext:
    """Условия точки, посчитанные один раз на посадку и общие для всех видов.

    clearance_m - минимальное измеренное расстояние до объекта каждого класса. Классы, по
    которым в чертеже нет данных (исход no_data), в словарь не попадают: «не измерено» и
    «далеко» - разные вещи, и фильтр обязан их различать.
    """

    placement_id: str
    x: float
    y: float
    clearance_m: Mapping[ObjectClass, float]
    under_overhead_line: bool
    structure_id: str | None = None
    structure_kind: str | None = None  # row | group | single


def site_context(
    placement: Placement,
    structure_id: str | None = None,
    structure_kind: str | None = None,
) -> SiteContext:
    clearance: dict[ObjectClass, float] = {}
    under_line = False
    for check in placement.checks:
        if check.object_class is None:
            continue
        if check.object_class is ObjectClass.POWER_LINE_OVERHEAD:
            under_line = under_line or check.outcome is CheckOutcome.FAIL
        if check.measured_m is None:
            continue
        current = clearance.get(check.object_class)
        if current is None or check.measured_m < current:
            clearance[check.object_class] = check.measured_m
    return SiteContext(
        placement_id=placement.placement_id,
        x=placement.x,
        y=placement.y,
        clearance_m=clearance,
        under_overhead_line=under_line,
        structure_id=structure_id,
        structure_kind=structure_kind,
    )


def nearest_clearance(ctx: SiteContext, classes: Iterable[ObjectClass]) -> float | None:
    """Ближайший из перечисленных классов или None, если ни один не измерен."""
    measured = [ctx.clearance_m[c] for c in classes if c in ctx.clearance_m]
    return min(measured) if measured else None
