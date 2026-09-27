"""Shared checks before either generating or auditing a planting plan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from green.application.errors import InputError
from green.application.wording import counted, plural

if TYPE_CHECKING:
    from green.domain.objects import Scene

# Пробелов чтения в тексте ошибки не больше стольких: полный учёт - в журнале чтения.
_DETAILS_LIMIT = 20


def require_complete_geometry(scene: Scene) -> None:
    """Reject missing spatial information, including losses outside INSERTs.

    Первая фраза ошибки - для человека: что не прочитано и сколько. Страница неудавшегося
    прогона ставит её заголовком, поэтому кодов причин, ссылок на объекты и путей в ней нет:
    они идут после слова «Подробности».
    """
    diagnostics = scene.read_diagnostics
    problems = [
        *(f"XREF {name}" for name in diagnostics.unresolved_xrefs),
        *diagnostics.block_failures,
        *(
            f"{gap.entity_type}, слой {gap.layer!r}, блок {gap.block!r}: "
            f"{gap.count} ({gap.reason}), примеры {', '.join(gap.source_refs[:2])}"
            for gap in diagnostics.geometry_gaps
        ),
    ]
    if not problems:
        return
    xrefs = len(diagnostics.unresolved_xrefs)
    lost = sum(gap.count for gap in diagnostics.geometry_gaps) + sum(
        diagnostics.skipped_by_type.get(kind, 0) for kind in diagnostics.block_failures
    )
    raise InputError(
        f"{_headline(xrefs, lost)} {_advice(xrefs=xrefs > 0, lost=lost > 0)} "
        f"Подробности: {'; '.join(problems[:_DETAILS_LIMIT])}."
    )


def _headline(xrefs: int, lost: int) -> str:
    parts = []
    if xrefs:
        links = counted(xrefs, "внешняя ссылка", "внешние ссылки", "внешних ссылок")
        parts.append(f"не {plural(xrefs, 'найдена', 'найдены', 'найдено')} {links}")
    if lost:
        parts.append(f"у {counted(lost, 'объекта', 'объектов', 'объектов')} нет геометрии")
    if not parts:
        return "Чертёж прочитан не полностью."
    return f"Чертёж прочитан не полностью: {', '.join(parts)}."


def _advice(*, xrefs: bool, lost: bool) -> str:
    if xrefs and lost:
        fix = (
            "сохраните DXF вместе с внешними ссылками, а неподдерживаемые объекты замените "
            "полилиниями или штриховками"
        )
    elif xrefs:
        fix = "сохраните DXF вместе с внешними ссылками"
    else:
        fix = "замените неподдерживаемые объекты полилиниями или штриховками и сохраните DXF"
    return f"Расчёт остановлен: {fix}. Наличие других сетей не заменяет потерянные данные."
