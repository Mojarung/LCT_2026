"""Совмещение слоя ГИС с чертежом: насколько здания слоя попадают на здания подосновы.

Пересчёт WGS 84 -> МСК-Москва приближённый, а слой могли выгрузить не в той системе. Здания -
самый надёжный общий объект слоя data.mos.ru и подосновы Мосгеотреста: для каждого здания
слоя ищется ближайшее здание чертежа, медиана расстояний между центрами - оценка сдвига.
Сервис её не исправляет, а сообщает: сдвиг больше порога значит, что охранные зоны и прочие
объекты слоя легли не туда, и план по ним проверять нельзя.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely import STRtree

from green.application.wording import counted, decimal
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.domain.objects import Feature

# Здание слоя дальше этого от любого здания чертежа - не пара, а здание вне подосновы.
PAIR_LIMIT_M = 50.0
# Медианный сдвиг больше этого - слой лёг не туда (точность подосновы 1:500 - доли метра).
SHIFT_WARNING_M = 3.0


def alignment_notes(
    layer: Sequence[Feature], drawing: Sequence[Feature]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(заметки, предупреждения) о совмещении зданий слоя ГИС со зданиями чертежа."""
    ours = [f.geometry for f in drawing if f.object_class is ObjectClass.BUILDING]
    theirs = [f.geometry for f in layer if f.object_class is ObjectClass.BUILDING]
    if not ours or not theirs:
        return (), ()
    centres = shapely.centroid(shapely.convex_hull(np.asarray(ours, dtype=object)))
    tree = STRtree(centres)
    probes = shapely.centroid(shapely.convex_hull(np.asarray(theirs, dtype=object)))
    _, distances = tree.query_nearest(probes, return_distance=True, all_matches=False)
    paired = distances[distances <= PAIR_LIMIT_M]
    if not len(paired):
        return (), (
            (
                "Слой ГИС: ни одно здание слоя не легло на здание чертежа ближе "
                f"{PAIR_LIMIT_M:.0f} м - проверьте систему координат слоя"
            ),
        )
    shift = float(np.median(paired))
    note = (
        f"Слой ГИС совмещён с чертежом по {counted(len(paired), 'зданию', 'зданиям', 'зданиям')}: "
        f"медиана расстояния между центрами {decimal(shift, 2)} м"
    )
    if shift > SHIFT_WARNING_M:
        return (), (
            (
                f"{note} - больше {decimal(SHIFT_WARNING_M)} м: объекты слоя легли со сдвигом, "
                "проверьте систему координат слоя"
            ),
        )
    return (note,), ()
