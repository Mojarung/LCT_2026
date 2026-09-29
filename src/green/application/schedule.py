"""Ведомость посадочного материала: количества по видам, размеры кома и площадь посадочных ям.

Заказчик назвал неверно посчитанные объёмы второй причиной возврата проектов после отступов
(docs/notes/15-organizers-qa.md, вопрос 14). Графы повторяют ведомость проектировщика из
датасета («8. Лодочная/Проектное решение/Таблица ассортимента деревьев и кустарников.xlsx»):
номер, наименование, количество, стандарт, размер кома, площадь под посадочные ямы, разделы по
хвойным и лиственным деревьям и кустарникам с итогами.

Стандарт посадочного материала по жизненной форме - параметр проекта в духе 515-ПП (раздел 4:
деревья IV группы с комом 1,3 x 1,3 x 0,6 м, малые деревья с комом 1,0 x 1,0 x 0,6 м).
Размер ямы под ком берётся из 743-ПП, табл. 3.3.1. Площадь под ямы = количество x площадь ямы.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from green.domain.planting import LifeForm

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.domain.planting import Placement, Species

PIT_SOURCE = "743-ПП, табл. 3.3.1"


@dataclass(frozen=True, slots=True)
class Stock:
    """Стандарт саженца: группа, размер кома и яма под него."""

    group: str
    ball: str
    pit: str
    pit_area_m2: float


_SQUARE_13 = Stock("IV группа", "1,3x1,3x0,6", "2,2x2,2x0,85", 2.2 * 2.2)
_SQUARE_10 = Stock("III группа", "1,0x1,0x0,6", "1,9x1,9x0,85", 1.9 * 1.9)
_ROUND_05 = Stock("саженец с комом", "d=0,5; h=0,4", "d=1,0; h=0,65", math.pi * 0.5**2)
STOCK_BY_FORM = {
    LifeForm.TREE_LARGE: _SQUARE_13,
    LifeForm.TREE_MEDIUM: _SQUARE_13,
    LifeForm.TREE_SMALL: _SQUARE_10,
    LifeForm.SHRUB_TALL: _ROUND_05,
    LifeForm.SHRUB_MEDIUM: _ROUND_05,
    LifeForm.SHRUB_LOW: _ROUND_05,
}
SECTIONS = ("Хвойные деревья", "Лиственные деревья", "Хвойные кустарники", "Лиственные кустарники")


@dataclass(frozen=True, slots=True)
class ScheduleRow:
    number: int
    section: str
    name_ru: str
    name_lat: str
    count: int
    stock: Stock
    conditions: tuple[str, ...]
    # Код вида каталога: по нему посадка в DXF получает позицию своей строки (атрибут POS).
    code: str

    @property
    def pit_area_m2(self) -> float:
        return round(self.count * self.stock.pit_area_m2, 2)


def section_of(species: Species) -> str:
    kind = "деревья" if species.is_tree else "кустарники"
    return f"{'Хвойные' if species.is_conifer else 'Лиственные'} {kind}"


def build_schedule(placements: Sequence[Placement]) -> tuple[ScheduleRow, ...]:
    """Строка на вид, разделы в порядке SECTIONS, внутри раздела по названию."""
    counts: Counter[str] = Counter()
    species_by_code: dict[str, Species] = {}
    conditions: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for placement in placements:
        species = placement.species
        if species.life_form not in STOCK_BY_FORM:
            continue
        counts[species.code] += 1
        species_by_code[species.code] = species
        if placement.assortment is not None:
            for reason in placement.assortment.reasons:
                if reason.condition:
                    # «со стороны силового кабеля» у каждой посадки своё: в ведомости - суть.
                    conditions[species.code][reason.condition.split(" со стороны")[0]] += 1
    ordered = sorted(
        species_by_code.values(),
        key=lambda s: (SECTIONS.index(section_of(s)), s.name_ru),
    )
    return tuple(
        ScheduleRow(
            number=number,
            section=section_of(species),
            name_ru=species.name_ru,
            name_lat=species.name_lat,
            count=counts[species.code],
            stock=STOCK_BY_FORM[species.life_form],
            conditions=tuple(
                f"{text}: {count} шт." for text, count in sorted(conditions[species.code].items())
            ),
            code=species.code,
        )
        for number, species in enumerate(ordered, 1)
    )
