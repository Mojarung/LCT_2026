"""Ошибки прикладного слоя, которые интерфейсы переводят в понятные ответы."""

from __future__ import annotations


class GreenError(Exception):
    """Базовая ошибка сервиса."""


class InputError(GreenError):
    """Входной файл или параметры не подходят для прогона."""


class ConfigurationError(GreenError):
    """Конфигурация норм, слоёв или профилей некорректна."""


class ConversionError(GreenError):
    """Не удалось перевести чертёж в DXF."""


class NotFoundError(GreenError):
    """Запрошенный объект не существует."""
