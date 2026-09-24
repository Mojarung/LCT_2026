"""Русские числительные и числа в текстах предупреждений.

Предупреждения показываются в интерфейсе рядом с числом посадок и уходят в выгрузку, их
читает эксперт: «4 участков, 63 кустов» выдаёт шаблон и подрывает доверие к остальному тексту.
"""

from __future__ import annotations


def plural(count: int, one: str, few: str, many: str) -> str:
    """Форма слова при числе: 1 участок, 2 участка, 5 участков; 11-14 - всегда «многих»."""
    tail = count % 10
    hundred = count % 100
    if tail == 1 and hundred != 11:  # noqa: PLR2004 - правило языка, не порог
        return one
    if 2 <= tail <= 4 and not 12 <= hundred <= 14:  # noqa: PLR2004 - правило языка, не порог
        return few
    return many


def counted(count: int, one: str, few: str, many: str) -> str:
    """Число со словом в нужной форме: «63 куста»."""
    return f"{count} {plural(count, one, few, many)}"


def _decimal(value: float, digits: int) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def index_change(before: float, after: float) -> str:
    """Изменение индекса качества: сотых хватает, пока они различаются, иначе тысячные."""
    digits = 2 if _decimal(before, 2) != _decimal(after, 2) else 3
    return f"{_decimal(before, digits)} -> {_decimal(after, digits)}"
