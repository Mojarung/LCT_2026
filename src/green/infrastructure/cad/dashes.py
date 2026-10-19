"""Пунктир, разобранный на штрихи: штрихи одной линии сшиваются обратно в линию.

MicroStation при выгрузке в DWG пишет линию со стилем «пунктир» не одной сущностью с типом
линии, а отдельными отрезками-штрихами: в блоке msdElementType* на каждый элемент или прямо в
блоке листа. У Кустанайской 9 895 штрихов борта по 0,71 м с разрывом ровно 0,5 м. Для расчёта
это не линия, а решето: разлив подписи покрытия уходил в разрывы, проезд шёл зубцами, а
перемычки по близости концов соединяли штрихи соседних линий наискось (19.10.2026).

В чертеже штрихи одной линии идут подряд, и конец штриха смотрит на начало следующего: по
этому признаку линия восстанавливается точно, без угадывания. Вершина, попавшая в разрыв,
восстанавливается пересечением продолжений соседних штрихов. Штрихи, которые друг на друга не
смотрят (бергштрихи откоса, заливка точки полосы деревьев, рисунок знака), не сшиваются.

Прерывистая линия в смысле CAD (тип линии с разрывами в таблице LTYPE) - тот же смысл, но
геометрия у неё уже сплошная: ридер только ставит ей флаг dashed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely.geometry import LineString

if TYPE_CHECKING:
    from collections.abc import Sequence

    from green.domain.objects import Feature

# Разрыв пунктира не длиннее этого: у Мосгеотреста 0,5 м, в паспорте ОГХ (тип линии 189)
# 0,75 м. Въезд, калитка и проход шире: они остаются разрывами.
GAP_MAX_M = 0.8
# Разрыв продолжает штрих: направление разрыва и обоих штрихов расходится не больше чем на это.
# Штрих на круге клумбы радиусом 2 м - хорда: у разрыва 0,74 м расхождение доходит до 22°, и
# при пороге 20° круг на Харьковской оставался двумя дугами.
ALONG_DEG = 30.0
# Концы ближе этого - один узел: так сходятся отрезки разобранной сплошной ломаной.
TOUCH_M = 1e-4
# Штрих не длиннее этого (у Мосгеотреста 0,71-0,75 м, в паспорте ОГХ 0,75 м). Длинный отрезок -
# стена или борт, а не штрих: стены школы на Харьковской, сшитые с соседними кусками через
# разрыв, получали признак пунктира и пропадали из объёмов (19.10.2026).
DASH_MAX_M = 2.0
# Пунктир - это ряд штрихов: цепочка с одним разрывом скорее стена с дверным проёмом или
# стыком листов, чем пунктир (Харьковская: кусок стены школы у входа получал признак пунктира,
# и школа пропадала из объёмов). Пунктиром считается цепочка хотя бы с тремя разрывами.
MIN_GAPS = 3
# Продолжения штрихов почти параллельны - вершины между ними нет.
_PARALLEL_SIN = math.sin(math.radians(5.0))
_COS_ALONG = math.cos(math.radians(ALONG_DEG))
# Вершина ближе этого к концу штриха - тот же конец (единицы чертежа: погрешность округления).
_SAME_M = 1e-9

type _Point = tuple[float, float]


def chain_dashes(features: Sequence[Feature], *, parent: str, unit_m: float = 1.0) -> list[Feature]:
    """Штрихи - прямые потомки вставки parent - подряд в порядке чертежа сшиваются в линию.

    Цепочка встаёт на место первого штриха, с его ссылкой и флагом dashed; цепочка без единого
    разрыва (разобранная сплошная ломаная) остаётся как была. Прочие объекты не трогаются, и
    порядок сохраняется. Пороги - метры, unit_m - размер единицы чертежа."""
    gap_max, touch, longest = GAP_MAX_M / unit_m, TOUCH_M / unit_m, DASH_MAX_M / unit_m
    out: list[Feature] = []
    run: list[Feature] = []
    path: list[_Point] = []
    gaps = 0

    def flush() -> None:
        nonlocal run, path, gaps
        if len(run) > 1 and gaps >= MIN_GAPS:
            out.append(_merged(run, path))
        else:
            out.extend(run)
        run, path, gaps = [], [], 0

    for feature in features:
        if not _dash(feature, parent, longest):
            flush()
            out.append(feature)
            continue
        coords = [(float(x), float(y)) for x, y, *_ in feature.geometry.coords]
        joined = None
        if run and feature.layer == run[0].layer and feature.block == run[0].block:
            joined = _link(path, coords, gap_max, touch)
            if joined is None and len(run) == 1:
                # Первый штрих мог быть записан навстречу: проверяется и он.
                joined = _link(path[::-1], coords, gap_max, touch)
                if joined is not None:
                    path.reverse()
        if joined is None:
            flush()
            run, path = [feature], coords
            continue
        points, gap = joined
        run.append(feature)
        path.extend(points)
        gaps += gap
    flush()
    return _stitched(out, parent, (gap_max, touch, longest))


@dataclass(slots=True)
class _Path:
    coords: list[_Point]
    # Места штрихов и цепочек пути в списке объектов вставки.
    members: list[int]
    # Разрывы пути: у готовой пунктирной цепочки их заведомо не меньше MIN_GAPS.
    gaps: int

    @property
    def dashed(self) -> bool:
        return self.gaps >= MIN_GAPS


def _stitched(
    features: list[Feature], parent: str, limits: tuple[float, float, float]
) -> list[Feature]:
    """Цепочки одной линии, разорванные порядком записи, сшиваются концами.

    На Харьковской лист пишет штрих, в который попала вершина, кусками далеко от соседних
    штрихов (через 35 тыс. записей): подряд линия собиралась отрезками с разрывом 1,7 м, где
    этот кусок и лежит. Концы цепочек и штрихов одного слоя ищутся рядом друг с другом и
    сшиваются по тому же признаку, что подряд; две сплошные части концами не сшиваются.
    Замкнутые контуры замыкаются здесь же."""
    gap_max, touch, longest = limits
    groups: dict[tuple[str, str | None], list[int]] = {}
    for i, feature in enumerate(features):
        if _dash(feature, parent, longest):
            groups.setdefault((feature.layer, feature.block), []).append(i)
    placed: dict[int, Feature] = {}
    dropped: set[int] = set()
    for indices in groups.values():
        paths = [
            _Path(
                [(float(x), float(y)) for x, y, *_ in features[i].geometry.coords],
                [i],
                MIN_GAPS if features[i].dashed else 0,
            )
            for i in indices
        ]
        for path in _joined(paths, gap_max, touch):
            if not path.dashed:
                continue
            members = sorted(path.members)
            ring = _closed(path.coords, gap_max, touch)
            placed[members[0]] = _merged([features[m] for m in members], ring)
            dropped.update(members[1:])
    return [placed.get(i, f) for i, f in enumerate(features) if i not in dropped]


def _joined(paths: list[_Path], gap_max: float, touch: float) -> list[_Path]:
    """Сшивка концов кругами: в круге каждая цепочка входит не больше чем в одну сшивку."""
    while len(paths) > 1:
        ends = shapely.points(
            [point for path in paths for point in (path.coords[0], path.coords[-1])]
        )
        tree = shapely.STRtree(ends)
        a, b = tree.query(ends, predicate="dwithin", distance=gap_max)
        keep = (a // 2) < (b // 2)
        a, b = a[keep], b[keep]
        if not len(a):
            break
        order = np.argsort(shapely.distance(ends[a], ends[b]), kind="stable")
        used: set[int] = set()
        merged: list[_Path] = []
        for k in order:
            pa, sa = divmod(int(a[k]), 2)
            pb, sb = divmod(int(b[k]), 2)
            if pa in used or pb in used:
                continue
            first = paths[pa].coords if sa == 1 else paths[pa].coords[::-1]
            second = paths[pb].coords if sb == 0 else paths[pb].coords[::-1]
            joined = _link(first, second, gap_max, touch, both=False)
            if joined is None:
                continue
            points, gap = joined
            if not (gap or paths[pa].dashed or paths[pb].dashed):
                continue
            used.update((pa, pb))
            merged.append(
                _Path(
                    [*first, *points],
                    [*paths[pa].members, *paths[pb].members],
                    paths[pa].gaps + paths[pb].gaps + gap,
                )
            )
        if not merged:
            break
        paths = [path for i, path in enumerate(paths) if i not in used] + merged
    return paths


def _dash(feature: Feature, parent: str, longest: float) -> bool:
    """Штрих или уже сшитая пунктирная цепочка: открытая линия - прямой потомок вставки, не
    часть знака, короче longest, если сама не пунктир."""
    geometry = feature.geometry
    handle = feature.ref.handle
    prefix = f"{parent}~"
    return (
        handle.startswith(prefix)
        and handle[len(prefix) :].isdigit()
        and geometry.geom_type == "LineString"
        and not geometry.is_closed
        and geometry.length > 0
        and (feature.dashed or geometry.length <= longest)
        and feature.symbol is None
        and feature.circle_radius_m is None
        and feature.uncertainty_footprint is None
    )


def _link(
    path: list[_Point], piece: list[_Point], gap_max: float, touch: float, *, both: bool = True
) -> tuple[list[_Point], int] | None:
    """Точки, которыми штрих продолжает путь, и был ли между ними разрыв; None - не продолжает.
    both=False - штрих только в своём направлении."""
    end, heading = path[-1], _heading(path)
    for candidate in (piece, piece[::-1]) if both else (piece,):
        start = candidate[0]
        gx, gy = start[0] - end[0], start[1] - end[1]
        gap = math.hypot(gx, gy)
        if gap <= touch:
            return candidate[1:], 0
        if gap > gap_max or heading is None:
            continue
        onward = _heading(candidate[::-1], forward=False)
        if onward is None:
            continue
        ux, uy = gx / gap, gy / gap
        if (
            heading[0] * ux + heading[1] * uy >= _COS_ALONG
            and ux * onward[0] + uy * onward[1] >= _COS_ALONG
        ):
            return candidate, 1
        corner = _corner(end, heading, start, onward, gap_max, touch)
        if corner is not None:
            return [*_new(corner, end, start), *candidate], 1
    return None


def _heading(path: list[_Point], *, forward: bool = True) -> _Point | None:
    """Направление последнего ненулевого звена пути (forward=False - первого, развёрнутое)."""
    end = path[-1]
    for point in reversed(path[:-1]):
        dx, dy = end[0] - point[0], end[1] - point[1]
        length = math.hypot(dx, dy)
        if length > 0:
            return (dx / length, dy / length) if forward else (-dx / length, -dy / length)
    return None


def _corner(  # noqa: PLR0913, PLR0917 - два луча и два порога
    end: _Point, heading: _Point, start: _Point, onward: _Point, gap_max: float, touch: float
) -> _Point | None:
    """Вершина в разрыве: продолжение штриха вперёд встречает продолжение следующего назад, и
    путь через неё не длиннее разрыва. Вершина может совпасть с концом штриха или началом
    следующего: штрих оборвался ровно на изломе."""
    det = heading[0] * onward[1] - heading[1] * onward[0]
    if abs(det) < _PARALLEL_SIN:
        return None
    gx, gy = start[0] - end[0], start[1] - end[1]
    t = (gx * onward[1] - gy * onward[0]) / det
    s = (heading[0] * gy - heading[1] * gx) / det
    if t < -touch or s < -touch or t + s > gap_max:
        return None
    return (end[0] + t * heading[0], end[1] + t * heading[1])


def _new(corner: _Point, end: _Point, start: _Point) -> list[_Point]:
    """Вершина в разрыве, если она не совпала с концом штриха или началом следующего."""
    same = (end, start)
    return [] if any(math.dist(corner, p) <= _SAME_M for p in same) else [corner]


def _closed(path: list[_Point], gap_max: float, touch: float) -> list[_Point]:
    """Контур (элемент «shape»): конец смотрит на начало через разрыв - кольцо замыкается."""
    first, end = path[0], path[-1]
    heading, onward = _heading(path), _heading(path[1::-1], forward=False)
    gap = math.hypot(first[0] - end[0], first[1] - end[1])
    if len(path) < 3 or heading is None or onward is None or gap > gap_max:  # noqa: PLR2004 - кольцу нужны три точки
        return path
    if gap <= touch:
        return [*path[:-1], first]
    ux, uy = (first[0] - end[0]) / gap, (first[1] - end[1]) / gap
    if (
        heading[0] * ux + heading[1] * uy >= _COS_ALONG
        and ux * onward[0] + uy * onward[1] >= _COS_ALONG
    ):
        return [*path, first]
    corner = _corner(end, heading, first, onward, gap_max, touch)
    return path if corner is None else [*path, *_new(corner, end, first), first]


def _merged(run: list[Feature], path: list[_Point]) -> Feature:
    errors = [f.geometry_error_m for f in run]
    return replace(
        run[0],
        geometry=LineString(path),
        dashed=True,
        geometry_error_m=None if None in errors else max(e or 0.0 for e in errors),
    )
