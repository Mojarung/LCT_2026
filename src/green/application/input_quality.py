"""Shared checks before either generating or auditing a planting plan."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from green.application.errors import InputError
from green.application.wording import counted, decimal_g, plural

if TYPE_CHECKING:
    from green.domain.objects import Scene

# Пробелов чтения в тексте ошибки не больше стольких: полный учёт - в журнале чтения.
_DETAILS_LIMIT = 20
UNBOUNDED_APPROXIMATION = "approximation-error-not-bounded"
# Запас отступа от кривой без доказанной погрешности (сплайн без контрольных точек, сглаженная
# полилиния): допуск аппроксимации ридера - сантиметры, полметра покрывает его с избытком.
ASSUMED_ERROR_M = 0.5


def require_complete_geometry(scene: Scene) -> None:
    """Reject missing spatial information, including losses outside INSERTs.

    Первая фраза ошибки - для человека: что не прочитано и сколько. Страница неудавшегося
    прогона ставит её заголовком, поэтому кодов причин, ссылок на объекты и путей в ней нет:
    они идут после слова «Подробности».
    """
    found = _missing(scene)
    if found is None:
        return
    problems, xrefs, lost = found
    raise InputError(
        f"{_headline(xrefs, lost)} {_advice(xrefs=xrefs > 0, lost=lost > 0)} "
        f"Подробности: {'; '.join(problems[:_DETAILS_LIMIT])}."
    )


def incomplete_geometry_note(scene: Scene) -> str | None:
    """То же, что require_complete_geometry, но предупреждением: расчёт идёт по прочитанному.

    Чужой чертёж (внешняя ссылка не приложена, тело без данных ACIS, неизвестный объект) не
    останавливает прогон: план строится по прочитанному, а журнал называет, чего в нём нет и
    что посадки у этих мест по ним не проверены (20.10.2026). strict_input=true - остановка.
    """
    found = _missing(scene, approximations=False)
    if found is None:
        return None
    problems, xrefs, lost = found
    return (
        f"{_headline(xrefs, lost)} Расчёт продолжен по прочитанному: посадки у "
        "непрочитанных объектов по ним не проверены - проверьте эти места в CAD; "
        f"{_fix(xrefs=xrefs > 0, lost=lost > 0)}, чтобы проверка была полной. Чтобы такой "
        "чертёж останавливал расчёт, запустите с strict_input=true. "
        f"Подробности: {'; '.join(problems[:_DETAILS_LIMIT])}."
    )


def with_assumed_errors(scene: Scene) -> tuple[Scene, str | None]:
    """Кривые без доказанной погрешности аппроксимации получают запас ASSUMED_ERROR_M.

    Строгий режим такие объекты не принимает (погрешность не установлена - план не
    сертифицируется); по умолчанию нормы меряются от них с запасом, и журнал это называет."""
    unbounded = [f for f in scene.features if f.geometry_error_m is None]
    if not unbounded:
        return scene, None
    features = tuple(
        replace(f, geometry_error_m=ASSUMED_ERROR_M) if f.geometry_error_m is None else f
        for f in scene.features
    )
    kinds = Counter(f.source_entity_type or "?" for f in unbounded)
    details = ", ".join(f"{kind} {count}" for kind, count in kinds.most_common(6))
    note = (
        f"Исправлено автоматически: у {counted(len(unbounded), 'кривой', 'кривых', 'кривых')} "
        f"погрешность аппроксимации не доказана ({details}) - отступы от них меряются с "
        f"запасом {decimal_g(ASSUMED_ERROR_M)} м."
    )
    return replace(scene, features=features), note


def _missing(scene: Scene, *, approximations: bool = True) -> tuple[list[str], int, int] | None:
    diagnostics = scene.read_diagnostics
    gaps = [
        gap
        for gap in diagnostics.geometry_gaps
        if approximations or gap.reason != UNBOUNDED_APPROXIMATION
    ]
    problems = [
        *(f"XREF {name}" for name in diagnostics.unresolved_xrefs),
        *diagnostics.block_failures,
        *(
            f"{gap.entity_type}, слой {gap.layer!r}, блок {gap.block!r}: "
            f"{gap.count} ({gap.reason}), примеры {', '.join(gap.source_refs[:2])}"
            for gap in gaps
        ),
    ]
    if not problems:
        return None
    xrefs = len(diagnostics.unresolved_xrefs)
    lost = sum(gap.count for gap in gaps) + sum(
        diagnostics.skipped_by_type.get(kind, 0) for kind in diagnostics.block_failures
    )
    return problems, xrefs, lost


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
    return (
        f"Расчёт остановлен: {_fix(xrefs=xrefs, lost=lost)}. Наличие других сетей не "
        "заменяет потерянные данные."
    )


def _fix(*, xrefs: bool, lost: bool) -> str:
    if xrefs and lost:
        fix = (
            "сохраните DXF вместе с внешними ссылками, а неподдерживаемые объекты замените "
            "полилиниями или штриховками"
        )
    elif xrefs:
        fix = "сохраните DXF вместе с внешними ссылками"
    else:
        fix = "замените неподдерживаемые объекты полилиниями или штриховками и сохраните DXF"
    return fix
