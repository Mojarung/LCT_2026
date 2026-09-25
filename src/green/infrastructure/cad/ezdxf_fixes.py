"""Исправления ezdxf, без которых разбор настоящих чертежей теряет вставки.

`LeaderData.transform` (ezdxf 1.4.4) нормализует вектор полки мультивыноски; у полки нулевой
длины вектор нулевой, и перенос вставки падает делением на ноль. Ридер объявлял такую вставку
неразбираемой и терял весь её рисунок (одна выноска - весь рисунок внешней ссылки), сверка
чернил падала целиком (улица Берзарина, 25.09.2026). Полка нулевой длины на рисунок не
влияет: переносятся точки выноски, вектор полки остаётся как был. Документ не меняется -
исправлен только перенос копии.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ezdxf.entities.mleader import LeaderData

if TYPE_CHECKING:
    from ezdxf.entities.mleader import WCSTransform

_ORIGINAL = LeaderData.transform


def _transform(self: LeaderData, wcs: WCSTransform) -> None:
    if self.dogleg_length:
        _ORIGINAL(self, wcs)
        return
    m = wcs.m
    self.last_leader_point = m.transform(self.last_leader_point)
    self.breaks = list(m.transform_vertices(self.breaks))
    for line in self.lines:
        line.transform(wcs)


def install() -> None:
    """Поставить исправления; повторный вызов ничего не меняет."""
    LeaderData.transform = _transform
