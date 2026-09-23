"""Shared checks before either generating or auditing a planting plan."""

from __future__ import annotations

from typing import TYPE_CHECKING

from green.application.errors import InputError

if TYPE_CHECKING:
    from green.domain.objects import Scene


def require_complete_geometry(scene: Scene) -> None:
    """Reject missing spatial information, including losses outside INSERTs."""
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
    if problems:
        raise InputError(
            "Неполная геометрия входного чертежа: "
            + "; ".join(problems[:20])
            + ". Расчёт остановлен: загрузите внешние ссылки и предоставьте DXF с сохранённой "
            "пространственной геометрией (для неподдерживаемых объектов — полилинии/штриховки). "
            "Наличие других сетей не заменяет потерянные данные."
        )
