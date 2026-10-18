"""Тень зданий над местом посадки (ТЗ, п. 2: плотность застройки и типовые условия посадки).

Вид в каталоге несёт потребность в свете (`Species.light`: sun - светолюбив, semi - терпит
полутень). Тень над местом считается по объёмам зданий (application/volumes: основание и
высота по этажности) и положению солнца над Москвой в два дня сезона вегетации - 15 мая и
15 августа, каждый светлый час, когда солнце выше MIN_ELEVATION_DEG. Тень дома в час -
выпуклая оболочка основания и его копии, сдвинутой от солнца на высоту / tg(высоты солнца):
у вогнутого дома (буквой Г, П) тень чуть шире настоящей, место во дворе считается теневым
чуть чаще. Доля - часы в тени к светлым часам.

Солнце - формулы NOAA (склонение и уравнение времени по Спенсеру), как у 3D-вида
(frontend/src/scene3d/solar.ts): тени плана и снимка ложатся одинаково.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely import STRtree
from shapely.affinity import translate

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from green.application.volumes import BuildingVolume
    from green.domain.planting import Plan

MOSCOW_LAT = 55.75
MOSCOW_LON = 37.62
MSK_OFFSET_H = 3
# 15 мая и 15 августа: середина весны и конец лета сезона вегетации.
SEASON_DAYS = (135, 227)
HOURS = tuple(float(h) for h in range(5, 22))
# Солнце ниже - тени длиннее улицы, а света от него растению мало.
MIN_ELEVATION_DEG = 5.0


@dataclass(frozen=True, slots=True)
class Sun:
    elevation: float  # градусы над горизонтом
    azimuth: float  # градусы от севера по часовой


def sun_position(day_of_year: int, hours: float) -> Sun:
    """Солнце над Москвой в день года и час по московскому времени (NOAA)."""
    g = 2 * math.pi / 365 * (day_of_year - 1 + (hours - 12) / 24)
    decl = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    eq_time = 229.18 * (
        0.000075
        + 0.001868 * math.cos(g)
        - 0.032077 * math.sin(g)
        - 0.014615 * math.cos(2 * g)
        - 0.040849 * math.sin(2 * g)
    )
    minutes = hours * 60 + eq_time + 4 * MOSCOW_LON - 60 * MSK_OFFSET_H
    hour_angle = math.radians(minutes / 4 - 180)
    phi = math.radians(MOSCOW_LAT)
    cos_zenith = math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.cos(
        hour_angle
    )
    zenith = math.acos(min(1.0, max(-1.0, cos_zenith)))
    azimuth = math.degrees(
        math.atan2(
            math.sin(hour_angle),
            math.cos(hour_angle) * math.sin(phi) - math.tan(decl) * math.cos(phi),
        )
    )
    return Sun(elevation=90 - math.degrees(zenith), azimuth=(azimuth + 180 + 360) % 360)


class ShadeMap:
    """Тени зданий на каждый светлый час сезона; доля часов в тени для точек."""

    def __init__(self, buildings: Sequence[BuildingVolume]) -> None:
        self._hours: list[STRtree] = []
        self._shadows: list[np.ndarray] = []
        self.daylight_hours = 0
        solid = [b for b in buildings if b.height_m > 0 and not b.footprint.is_empty]
        footprints = [b.footprint for b in solid]
        heights = np.array([b.height_m for b in solid])
        for day in SEASON_DAYS:
            for hour in HOURS:
                sun = sun_position(day, hour)
                if sun.elevation < MIN_ELEVATION_DEG:
                    continue
                self.daylight_hours += 1
                if not footprints:
                    continue
                reach = heights / math.tan(math.radians(sun.elevation))
                away = math.radians(sun.azimuth + 180)
                dx, dy = math.sin(away) * reach, math.cos(away) * reach
                shadows = np.array(
                    [
                        shapely.convex_hull(shapely.union(fp, translate(fp, float(x), float(y))))
                        for fp, x, y in zip(footprints, dx, dy, strict=True)
                    ],
                    dtype=object,
                )
                self._shadows.append(shadows)
                self._hours.append(STRtree(shadows))

    def share(self, xy: NDArray[np.float64]) -> NDArray[np.float64]:
        """Доля светлых часов, когда точка в тени здания: 0 - солнце весь день, 1 - тень."""
        shaded = np.zeros(len(xy))
        if not self._hours or not len(xy):
            return shaded
        points = shapely.points(xy)
        for tree in self._hours:
            hit = np.zeros(len(xy), dtype=bool)
            pairs = tree.query(points, predicate="within")
            hit[pairs[0]] = True
            shaded += hit
        return shaded / self.daylight_hours


def with_shade(plan: Plan, shade: ShadeMap) -> Plan:
    """Доля тени каждой посадке, у которой её ещё нет."""
    open_ = [i for i, p in enumerate(plan.placements) if p.shade is None]
    if not open_:
        return plan
    xy = np.array([(plan.placements[i].x, plan.placements[i].y) for i in open_])
    found = shade.share(xy)
    placements = list(plan.placements)
    for i, value in zip(open_, found, strict=True):
        placements[i] = replace(placements[i], shade=round(float(value), 3))
    return replace(plan, placements=tuple(placements))


__all__ = ["HOURS", "SEASON_DAYS", "ShadeMap", "Sun", "sun_position", "with_shade"]
