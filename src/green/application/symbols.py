"""Словарь условных знаков: код блока -> класс объекта и роль знака (config/symbols.yaml).

Знак конкретнее слоя: слой говорит, в какой группе объектов знак нарисован, знак - что это
за объект. Дерево на подоснове - блок DEREVO из эллипса, круга и линии на слое «Полоса
деревьев»; по слою линия знака становилась газоном, а круг - вторым деревом.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from green.application.semantic_names import base_name

if TYPE_CHECKING:
    from collections.abc import Mapping

    from green.domain.objects import ObjectClass


class SymbolRole(StrEnum):
    # Объект в точке вставки (дерево, куст, колодец, опора); штрихи знака - его рисунок.
    POINT = "point"
    # Знак материала области (газон, лесной массив): отметка внутри контура, не объект.
    MARKER = "marker"
    # Штрихи знака сами контур объекта.
    GEOMETRY = "geometry"
    # Оформление (стрелка, скобка, пикет): в расчёт не идёт.
    ANNOTATION = "annotation"


@dataclass(frozen=True, slots=True)
class SymbolEntry:
    object_class: ObjectClass
    role: SymbolRole
    confirmed: bool = False
    note: str = ""


@dataclass(frozen=True, slots=True)
class SymbolCatalog:
    """Коды знаков по базовому имени блока (без префикса ссылки и номеров экземпляра)."""

    entries: Mapping[str, SymbolEntry] = field(default_factory=dict)
    fingerprint: str = ""

    def get(self, block: str) -> SymbolEntry | None:
        return self.entries.get(base_name(block))

    def __bool__(self) -> bool:
        return bool(self.entries)
