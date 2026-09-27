"""Что план даёт улице: баланс озеленения «было - стало», виды посадок и шумозащита.

Было - существующие насаждения чертежа (или перечётки), стало - они вместе с посадками плана.
Индекс качества оценивает план; этот блок описывает улицу и с индексом не смешивается.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

# Вид показателя: count - счёт штук и метров; norm - у показателя есть норма с числом;
# requirement - требование акта или заказчика без числа.
COUNT, NORM, REQUIREMENT = "count", "norm", "requirement"


@dataclass(frozen=True, slots=True)
class EffectMeasure:
    key: str
    title: str
    unit: str
    before: float | None
    after: float | None
    basis: str
    kind: str
    note: str = ""

    @property
    def delta(self) -> float | None:
        if self.before is None or self.after is None:
            return None
        return self.after - self.before


@dataclass(frozen=True, slots=True)
class PlantingKind:
    """Вид посадки плана по приёму размещения: штуки, погонные метры или площадь."""

    key: str
    title: str
    planting_type: str  # tree | shrub | lawn
    count: int
    basis: str
    length_m: float | None = None
    area_m2: float | None = None
    places: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NoiseBand:
    """Метры борта с полосой насаждений этой ширины (МГСН 1.02-02, табл. В.5)."""

    width: str  # «10-15», «16-20», «21-25», «26 и более»
    dba: str  # снижение по табл. В.5
    dba_sp276: str  # то же по СП 276.1325800, п. 7.8 (0,08 дБА на 1 м ширины)
    curb_before_m: float
    curb_after_m: float


@dataclass(frozen=True, slots=True)
class StreetEffect:
    measures: tuple[EffectMeasure, ...]
    kinds: tuple[PlantingKind, ...]
    noise: tuple[NoiseBand, ...]
    notes: tuple[str, ...] = ()
    stock_source: str = "none"
    # Знаменатели долей: по ним доли суммируются по нескольким улицам без искажения.
    area_m2: float = 0.0
    curb_m: float = 0.0
    length_m: float | None = None


__all__ = [
    "COUNT",
    "NORM",
    "REQUIREMENT",
    "EffectMeasure",
    "NoiseBand",
    "PlantingKind",
    "StreetEffect",
]
