"""Shared checks before either generating or auditing a planting plan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from green.application.errors import InputError

if TYPE_CHECKING:
    from green.domain.objects import Scene


def require_complete_blocks(scene: Scene) -> None:
    diagnostics = scene.read_diagnostics
    problems = [
        *(f"XREF {name}" for name in diagnostics.unresolved_xrefs),
        *diagnostics.block_failures,
    ]
    if problems:
        raise InputError(
            "Неполная геометрия блоков: "
            + "; ".join(problems[:20])
            + ". Расчёт остановлен: загрузите/внедрите внешние ссылки или предоставьте "
            "DXF с раскрываемыми блоками. Наличие других сетей не заменяет потерянные данные."
        )
