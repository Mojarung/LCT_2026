"""Числительные в текстах предупреждений: «4 участка, 63 куста», а не «4 участков, 63 кустов».

Предупреждения показываются в интерфейсе рядом с числом посадок, и эксперт читает их как
текст документа: ошибка в падеже выдаёт шаблон.
"""

from __future__ import annotations

import pytest

from green.application.wording import counted, index_change, plural


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (1, "участок"),
        (2, "участка"),
        (4, "участка"),
        (5, "участков"),
        (11, "участков"),
        (12, "участков"),
        (14, "участков"),
        (21, "участок"),
        (22, "участка"),
        (63, "участка"),
        (111, "участков"),
        (0, "участков"),
    ],
)
def test_plural_handles_the_teens(count: int, expected: str) -> None:
    assert plural(count, "участок", "участка", "участков") == expected


def test_counted_puts_the_number_before_the_word() -> None:
    assert counted(63, "куст", "куста", "кустов") == "63 куста"


def test_index_change_never_reads_as_no_change() -> None:
    """Сдвиг слабых мест поднимает индекс на тысячные: «0,87 -> 0,87» читается как «ничего»."""
    assert index_change(0.8712, 0.8738) == "0,871 -> 0,874"
    assert index_change(0.80, 0.83) == "0,80 -> 0,83"
