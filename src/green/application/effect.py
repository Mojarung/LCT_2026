"""Баланс озеленения и эффект плана для улицы: было - существующие насаждения, стало - они
вместе с посадками плана.

Показатели - те, что заказчик назвал признаками хорошего плана (docs/notes/15, вопрос 11:
тень, пылезащита, многоярусность, разнообразие), и итог перечётной ведомости (770-ПП, прил. 3:
деревья, кустарники, газоны). У каждого - основание и вид: норма с числом или требование без
числа. Числа существующих насаждений по чертежу - оценка (application/stock); точное число
деревьев даёт перечётная ведомость.

Шумозащита меряется шириной полосы насаждений у борта: снижение шума полосой задано только для
полос от 10 м (МГСН 1.02-02, табл. В.5, рекомендуемая: 10-15 м - 4-5 дБА; СП 276.1325800,
п. 7.8 - 0,08 дБА на 1 м ширины, то есть в 4 раза меньше). Ширина - отрезок нормали к борту в
зелени, начинающийся не дальше 2 м от борта; разрывы до 4 м полосу не обрывают.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.spatial import KDTree

from green.application.placement import (
    MODE_ALLEY,
    MODE_CURB_HEDGE,
    MODE_LABELS,
    MODE_LAWN,
    MODE_SHRUB_FILL,
    MODE_SHRUB_GROUP,
    MODE_SHRUB_ROW,
    MODE_UNDERSTORY,
)
from green.application.quality.coverage import FixedCrowns, fixed_crowns, measure_crowns
from green.application.quality.site import site_length, split_segments
from green.application.quality.terms import Layout
from green.application.stock import CIRCLE_SEGMENTS
from green.application.surfaces import Material
from green.application.wording import decimal
from green.domain.effect import (
    COUNT,
    NORM,
    REQUIREMENT,
    EffectMeasure,
    NoiseBand,
    PlantingKind,
    StreetEffect,
)
from green.domain.norms import LawnKind

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

    from green.application.params import PlanParams
    from green.application.ports import InventoryCounts
    from green.application.quality.site import Site
    from green.application.surfaces import SurfaceMap
    from green.domain.planting import Plan, Species

# Вид посадки по приёму: ключ, заголовок, основание термина, параметр шага для длины ряда.
_KINDS = (
    (
        MODE_ALLEY,
        "Аллея: рядовая посадка деревьев вдоль борта",
        "743-ПП, табл. 3.6.2; ГОСТ Р 71473-2024, п. 2.2.2.16",
        None,
    ),
    (MODE_LAWN, "Группы и одиночные деревья на газоне", "743-ПП, п. 10.8.1", None),
    (MODE_SHRUB_GROUP, "Группы кустарника на местах деревьев", "743-ПП, табл. 3.6.2, прим.", None),
    (
        MODE_SHRUB_ROW,
        "Ряд кустарника под кронами аллеи",
        "МГСН 1.02-02, п. 4.2.9.2",
        "shrub_row_spacing_m",
    ),
    (
        MODE_CURB_HEDGE,
        "Живая изгородь вдоль борта",
        "743-ПП, п. 2.1.13(1); ГОСТ Р 71473-2024, п. 2.2.2.27",
        "curb_hedge_spacing_m",
    ),
    (
        MODE_UNDERSTORY,
        "Кустарник под кронами деревьев: второй ярус",
        "МГСН 1.02-02, п. 4.2.9.2; СП 276.1325800, п. 7.8.2",
        None,
    ),
    (MODE_SHRUB_FILL, "Группы кустарника на газоне", "743-ПП, п. 10.8.1", None),
)
_BY_LABEL = {MODE_LABELS[key]: key for key, *_ in _KINDS}
_LAWN_BASIS = "743-ПП, п. 2.1.13; 770-ПП, прил. 3"

# МГСН 1.02-02, табл. В.5: ширина полосы, м -> снижение шума, дБА.
_BANDS = (
    (10.0, 16.0, "10-15", "4-5"),
    (16.0, 21.0, "16-20", "5-8"),
    (21.0, 26.0, "21-25", "8-10"),
    (26.0, math.inf, "26 и более", "10-12"),
)
SP276_DBA_PER_M = 0.08  # СП 276.1325800, п. 7.8.4
NOISE_STEP_M = 2.0  # шаг по борту
NOISE_RAY_M = 35.0  # дальше табл. В.5 не идёт
_RAY_STEP_M = 0.5
_START_M = 2.0  # полоса начинается у борта: не дальше этого от него
_GAP_M = 4.0  # разрыв до 4 м полосу не обрывает (СП 276, п. 7.8.2: шаг деревьев до 4 м)
_SHRUB_RADIUS_M = 0.5  # посадочное место куста, когда крона меньше


def street_effect(  # noqa: PLR0913 - план, участок, параметры и три необязательных входа
    plan: Plan,
    site: Site,
    params: PlanParams,
    inventory: InventoryCounts | None = None,
    *,
    surface: SurfaceMap | None = None,
    catalog: Sequence[Species] = (),
) -> StreetEffect:
    if site.boundary is None:
        return _without_boundary(plan, params)
    stock = site.stock
    layout = Layout.of(plan.placements)
    trees_new = int(layout.is_tree.sum())
    shrubs_new = int(layout.is_shrub.sum())
    length = site_length(site.boundary, params) if site.boundary is not None else None
    survey = _survey(inventory, catalog)
    trees_before, trees_note = _trees_before(site, survey)
    shrubs_before = survey.shrubs if survey is not None else stock.shrubs
    removed = survey.removed if survey is not None else 0
    base = _base(site, params, surface)
    shade = _shade(site, layout)
    curb = _curb(site, layout, params, base)
    tiers = _tiers(site, layout)
    noise = _noise(base, layout)
    kept = sum(g.area_m2 for g in plan.lawns if g.kind is LawnKind.KEPT)
    new = sum(g.area_m2 for g in plan.lawns if g.kind is LawnKind.NEW)
    new_species = {p.species.code for p in plan.placements}
    measures = [
        EffectMeasure(
            "trees",
            "Деревья",
            "шт.",
            trees_before,
            trees_before - removed + trees_new if trees_before is not None else None,
            "770-ПП, прил. 3 (итог перечётной ведомости)",
            COUNT,
            trees_note,
        ),
        EffectMeasure(
            "shrubs",
            "Кустарники",
            "шт.",
            shrubs_before,
            shrubs_before + shrubs_new,
            "770-ПП, прил. 3 (итог перечётной ведомости)",
            COUNT,
            "было - по перечётной ведомости"
            if survey is not None
            else "было - знаки кустарника чертежа; изгороди и массивы подосновы в штуках не "
            "считаются",
        ),
        *_share_pair(
            ("canopy_m2", "canopy_share", "м²"),
            "Тень: площадь взрослых крон",
            shade,
            site.area_m2,
            "вопрос 11 заказчика; СП 82.13330, п. 11.8",
            "площади участка",
        ),
        *_share_pair(
            ("curb_green_m", "curb_green_share", "м"),
            "Пылезащита: борта под кронами и нижним ярусом",
            curb,
            _length(site.curb_segments),
            "вопрос 11 заказчика; СП 82.13330, п. 9.38, 11.1",
            "длины бортов в границе работ",
        ),
        EffectMeasure(
            "tiers_trees",
            "Ярусность: деревья с кустарником под кроной",
            "шт.",
            tiers[0],
            tiers[1],
            "МГСН 1.02-02, п. 4.2.9.2; вопрос 11 заказчика",
            REQUIREMENT,
            ""
            if site.stock.source in {"symbols", "none"}
            else "существующие деревья - стволы, собранные из меток чертежа: оценка",
        ),
        EffectMeasure(
            "species_new",
            "Видов в новых посадках",
            "шт.",
            None,
            len(new_species),
            "вопрос 11 заказчика (биоразнообразие); 369-ПП",
            REQUIREMENT,
            _species_note(inventory, new_species),
        ),
        *_per_km(trees_before, trees_new, shrubs_before, shrubs_new, length, params),
        EffectMeasure(
            "lawn_m2",
            "Газон",
            "м²",
            round(kept, 1),
            round(kept + new, 1),
            _LAWN_BASIS,
            COUNT,
            "было - газон по чертежу вне посадочных мест плана; стало - с устраиваемым газоном",
        ),
        EffectMeasure(
            "noise_curb_m",
            "Шумозащита: борта с полосой насаждений от 10 м",
            "м",
            round(sum(b.curb_before_m for b in noise), 1) if noise else None,
            round(sum(b.curb_after_m for b in noise), 1) if noise else None,
            "МГСН 1.02-02, табл. В.5 (рекомендуемая); СП 276.1325800, п. 7.8",
            NORM,
            _NOISE_NOTE + (_NOISE_SIDE if surface is not None else _NOISE_BOTH),
        ),
    ]
    return StreetEffect(
        measures=tuple(measures),
        kinds=_kinds(plan, params),
        noise=noise,
        notes=_notes(site),
        stock_source=stock.source,
        area_m2=round(site.area_m2, 1),
        curb_m=round(_length(site.curb_segments), 1),
        length_m=round(length, 1) if length else None,
    )


_NOISE_NOTE = (
    "снижение по табл. В.5 МГСН 1.02-02 при однорядной или шахматной посадке; СП 276.1325800, "
    "п. 7.8 даёт 0,08 дБА на 1 м ширины (в 4 раза меньше) и требует шаг деревьев до 4 м, высоту "
    "от 5-8 м и подкроновое пространство, заполненное кустарником; у лиственных зимой эффект "
    "почти нулевой"
)


_NOISE_SIDE = (
    "; в счёт борта, у которых с одной стороны покрытие, полоса меряется в сторону грунта "
    "(проезжая часть в чертеже отдельно не выделена)"
)
_NOISE_BOTH = "; карты покрытий нет: полоса меряется в обе стороны от любого борта"


@dataclass(frozen=True, slots=True)
class _Survey:
    """Итог перечётки по 770-ПП, прил. 3: деревья и кусты всего (с вырубкой) и к вырубке."""

    trees: int
    shrubs: int
    removed: int


_SHRUB_NAME = "куст"


def _survey(inventory: InventoryCounts | None, catalog: Sequence[Species]) -> _Survey | None:
    if inventory is None:
        return None
    shrub_codes = {s.code for s in catalog if s.is_shrub}
    shrubs = sum(n for code, n in inventory.matched.items() if code in shrub_codes)
    shrubs += sum(n for name, n in inventory.unmatched.items() if _SHRUB_NAME in name.casefold())
    total = sum(inventory.matched.values()) + sum(inventory.unmatched.values())
    removed = inventory.removed
    return _Survey(trees=total - shrubs + removed, shrubs=shrubs, removed=removed)


def _without_boundary(plan: Plan, params: PlanParams) -> StreetEffect:
    """Без границы работ «было» не от чего считать: нет данных, а не ноль."""
    note = "нет данных: в чертеже не найдена граница работ"
    keys = (
        ("trees", "Деревья", "шт."),
        ("shrubs", "Кустарники", "шт."),
        ("canopy_m2", "Тень: площадь взрослых крон", "м²"),
        ("curb_green_m", "Пылезащита: борта под кронами и нижним ярусом", "м"),
        ("tiers_trees", "Ярусность: деревья с кустарником под кроной", "шт."),
        ("noise_curb_m", "Шумозащита: борта с полосой насаждений от 10 м", "м"),
    )
    return StreetEffect(
        measures=tuple(
            EffectMeasure(key, title, unit, None, None, "", REQUIREMENT, note)
            for key, title, unit in keys
        ),
        kinds=_kinds(plan, params),
        noise=(),
        notes=(note,),
    )


def _trees_before(site: Site, survey: _Survey | None) -> tuple[int | None, str]:
    stock = site.stock
    if survey is not None:
        note = f"было - по перечётной ведомости: {survey.trees}"
        if survey.removed:
            note += (
                f"; к вырубке {survey.removed} - решение проектировщика, сервис вырубку не "
                "назначает; стало - без вырубки и с новыми"
            )
        return survey.trees, note
    if not stock.marks and len(stock.strips_xy):
        return None, (
            "деревья в чертеже только полосами (знак полосы, а не стволы): число не "
            "определяется, площадь крон считается по полосам"
        )
    if not stock.marks:
        return 0, "существующих деревьев в чертеже нет"
    if stock.source == "symbols":
        return stock.trees, (
            "было - по знакам чертежа: одна вставка знака - одно дерево; точное число даёт "
            "перечётная ведомость"
        )
    # Разобранные знаки и знаки массивов: сверка 27.09.2026 - Багрицкого 1441 ствол по меткам
    # при 1228 деревьях дендрологического обоснования, Харьковская 428 при 724, Лодочная 4148
    # при 569. Штуки по таким меткам не показываются, площадь крон от дублей не растёт.
    return None, (
        f"по чертежу число деревьев не определяется: {stock.marks} меток разобранных знаков и "
        "знаков массивов; площадь крон считается по ним, число даёт перечётная ведомость"
    )


def _species_note(inventory: InventoryCounts | None, new: set[str]) -> str:
    if inventory is None:
        return "видов у существующих деревьев чертёж не называет"
    existing = set(inventory.matched)
    return (
        f"по перечётной ведомости существующих видов {len(existing)}, вместе с новыми "
        f"{len(existing | new)}"
    )


def _share_pair(  # noqa: PLR0913, PLR0917 - пара «величина и доля» одного показателя
    keys: tuple[str, str, str],
    title: str,
    values: tuple[float, float] | None,
    total: float,
    basis: str,
    of_what: str,
) -> list[EffectMeasure]:
    key, share_key, unit = keys
    if values is None or total <= 0:
        return [
            EffectMeasure(key, title, unit, None, None, basis, REQUIREMENT, "нет данных"),
            EffectMeasure(share_key, f"{title}, доля", "%", None, None, basis, REQUIREMENT),
        ]
    before, after = values
    return [
        EffectMeasure(key, title, unit, round(before, 1), round(after, 1), basis, REQUIREMENT),
        EffectMeasure(
            share_key,
            f"{title}, доля",
            "%",
            round(100 * before / total, 1),
            round(100 * after / total, 1),
            basis,
            REQUIREMENT,
            f"от {of_what}, {decimal(total, 0)} {unit}",
        ),
    ]


def _per_km(  # noqa: PLR0913, PLR0917 - было и стало по деревьям и кустарникам
    trees_before: int | None,
    trees_new: int,
    shrubs_before: int,
    shrubs_new: int,
    length: float | None,
    params: PlanParams,
) -> list[EffectMeasure]:
    km = length / 1000 if length else None
    out = []
    for key, title, before, new, (low, high) in (
        (
            "trees_per_km",
            "Деревьев на 1 км улицы",
            trees_before,
            trees_new,
            params.density_trees_per_km,
        ),
        (
            "shrubs_per_km",
            "Кустарников на 1 км улицы",
            shrubs_before,
            shrubs_new,
            params.density_shrubs_per_km,
        ),
    ):
        note = f"длина улицы {decimal(length, 0)} м" if length else "длина улицы неизвестна"
        if before is None and km:
            note += f"; существующие не посчитаны, новых {decimal(new / km, 1)} на 1 км"
        out.append(
            EffectMeasure(
                key,
                title,
                "шт./км",
                round(before / km, 1) if km and before is not None else None,
                round((before + new) / km, 1) if km and before is not None else None,
                f"МГСН 1.02-02, табл. В.1: {decimal(low, 0)}-{decimal(high, 0)} на 1 км",
                NORM,
                note,
            )
        )
    return out


def _circles(xy: np.ndarray, radius: np.ndarray) -> list[BaseGeometry]:
    if not len(xy):
        return []
    return list(shapely.buffer(shapely.points(xy), radius, quad_segs=CIRCLE_SEGMENTS))


def _shade(site: Site, layout: Layout) -> tuple[float, float] | None:
    if site.boundary is None:
        return None
    existing = site.stock.canopy
    before = float(existing.area) if existing is not None else 0.0
    trees = layout.is_tree
    circles = _circles(layout.xy[trees], layout.radius[trees])
    if not circles:
        return before, before
    planted = shapely.intersection(shapely.union_all(circles), site.boundary)
    after = shapely.union(planted, existing) if existing is not None else planted
    return before, float(after.area)


def _curb(
    site: Site, layout: Layout, params: PlanParams, base: _Base | None
) -> tuple[float, float] | None:
    if base is None or not len(site.curb_segments):
        return None
    new_r = np.where(layout.is_shrub, np.maximum(layout.radius, params.dust_strip_m), layout.radius)
    after = measure_crowns(
        site.curb_segments, layout.xy, new_r, np.ones(layout.size), fixed=base.curb
    ).covered_m
    return base.curb.covered_m, after


def _tiers(site: Site, layout: Layout) -> tuple[int, int]:
    """Деревья с кустарником под кроной: было - существующие с существующим кустом."""
    stock = site.stock
    trunks = stock.crown_xy[stock.crown_inside]
    r = stock.crown_radius
    old = KDTree(stock.shrubs_xy) if len(stock.shrubs_xy) else None
    shrub_xy = layout.xy[layout.is_shrub]
    new = KDTree(shrub_xy) if len(shrub_xy) else None
    before = after = 0
    for xy in trunks:
        had = old is not None and bool(old.query_ball_point(xy, r))
        before += had
        after += had or (new is not None and bool(new.query_ball_point(xy, r)))
    for i in np.flatnonzero(layout.is_tree).tolist():
        xy, radius = layout.xy[i], layout.radius[i]
        after += (new is not None and bool(new.query_ball_point(xy, radius))) or (
            old is not None and bool(old.query_ball_point(xy, radius))
        )
    return before, after


@dataclass(slots=True)
class _Base:
    """Всё «было» участка: считается один раз, правка плана пересчитывает только «стало».

    Отрезки борта с шагом NOISE_STEP_M, стороны у каждого (карта покрытий), ширина полосы до
    плана, покрытие бортов существующими кронами. last - последнее «стало» для этого участка:
    правка меняет одну-две посадки, и ширина полосы пересчитывается только у отрезков рядом.
    """

    mid: NDArray[np.float64]
    normal: NDArray[np.float64]
    lengths: NDArray[np.float64]
    sides: NDArray[np.float64]
    width_before: NDArray[np.float64]
    old_xy: NDArray[np.float64]
    old_r: NDArray[np.float64]
    curb: FixedCrowns
    samples: KDTree | None
    last: tuple[frozenset[tuple[float, float, float]], NDArray[np.float64]] | None = None


# Ключ - сами объекты участка и карты (ссылки держат их живыми): чужой участок с тем же id
# запись не получит. Несколько записей - несколько прогонов или правок в одном процессе.
_BASES: list[tuple[tuple[tuple[object, ...], tuple[object, ...]], _Base]] = []
_BASES_SIZE = 4


def clear_caches() -> None:
    _BASES.clear()


def _base(site: Site, params: PlanParams, surface: SurfaceMap | None) -> _Base | None:
    if not len(site.curb_segments):
        return None
    held = (site.stock, site.curb_segments, surface)
    values = (params.dust_strip_m,)
    for (objects, same), base in _BASES:
        if all(a is b for a, b in zip(objects, held, strict=True)) and same == values:
            return base
    crowns, radii = site.stock.crowns()
    shrubs = site.stock.shrubs_xy
    curb = fixed_crowns(
        site.curb_segments,
        np.vstack([crowns, shrubs]),
        np.concatenate([radii, np.full(len(shrubs), params.dust_strip_m)]),
        np.ones(len(crowns) + len(shrubs)),
    )
    old_xy = np.vstack([crowns, shrubs])
    old_r = np.concatenate([radii, np.full(len(shrubs), _SHRUB_RADIUS_M)])
    segments = split_segments(site.curb_segments, NOISE_STEP_M)
    lengths = np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1)
    keep = lengths > 0
    segments, lengths = segments[keep], lengths[keep]
    mid = segments.mean(axis=1)
    unit = (segments[:, 1] - segments[:, 0]) / lengths[:, None]
    normal = np.column_stack([-unit[:, 1], unit[:, 0]])
    sides = _green_sides(mid, normal, surface)
    width_before = _belt_width(mid, normal, _closed(_circles(old_xy, old_r)), sides)
    base = _Base(
        mid=mid,
        normal=normal,
        lengths=lengths,
        sides=sides,
        width_before=width_before,
        old_xy=old_xy,
        old_r=old_r,
        curb=curb,
        samples=KDTree(mid) if len(mid) else None,
    )
    _BASES.insert(0, ((held, values), base))
    del _BASES[_BASES_SIZE:]
    return base


def _closed(circles: list[BaseGeometry]) -> BaseGeometry | None:
    if not circles:
        return None
    half = _GAP_M / 2
    geometry = shapely.buffer(shapely.buffer(shapely.union_all(circles), half), -half)
    shapely.prepare(geometry)
    return geometry


def _noise(base: _Base | None, layout: Layout) -> tuple[NoiseBand, ...]:
    if base is None or not len(base.mid):
        return ()
    width_after = _width_after(base, layout)
    lengths, before = base.lengths, base.width_before
    return tuple(
        NoiseBand(
            width,
            dba,
            _sp276(low, high),
            round(float(lengths[(before >= low) & (before < high)].sum()), 1),
            round(float(lengths[(width_after >= low) & (width_after < high)].sum()), 1),
        )
        for low, high, width, dba in _BANDS
    )


def _width_after(base: _Base, layout: Layout) -> NDArray[np.float64]:
    """Ширина полосы после плана; пересчёт только у отрезков, до которых дотягиваются
    изменившиеся круги (луч NOISE_RAY_M, крона, разрыв _GAP_M), остальные - как было."""
    radius = np.where(layout.is_shrub, np.maximum(layout.radius, _SHRUB_RADIUS_M), layout.radius)
    circles = frozenset(
        (round(float(x), 3), round(float(y), 3), round(float(r), 3))
        for (x, y), r in zip(layout.xy, radius, strict=True)
    )
    if base.last is None:
        changed, width = circles, base.width_before.copy()
    else:
        changed, width = circles ^ base.last[0], base.last[1].copy()
    if changed and base.samples is not None:
        spots = np.array([(x, y) for x, y, _ in changed])
        top = max((r for *_, r in changed), default=0.0)
        top = max(top, float(base.old_r.max()) if len(base.old_r) else 0.0)
        reach = NOISE_RAY_M + top + _GAP_M
        near = sorted({i for hits in base.samples.query_ball_point(spots, reach) for i in hits})
        if near:
            width[near] = _local_width(base, near, layout.xy, radius, reach)
    base.last = (circles, width)
    return width


def _local_width(
    base: _Base,
    near: list[int],
    new_xy: NDArray[np.float64],
    new_r: NDArray[np.float64],
    reach: float,
) -> NDArray[np.float64]:
    """Ширина полосы у выбранных отрезков по зелени, собранной только из кругов рядом с ними:
    дальше reach круг на луч отрезка не влияет, поэтому итог тот же, что по всей улице."""
    mid = base.mid[near]
    xy = np.vstack([base.old_xy, new_xy])
    r = np.concatenate([base.old_r, new_r])
    if not len(xy):
        return np.zeros(len(near))
    tree = KDTree(xy)
    ids = sorted({j for hits in tree.query_ball_point(mid, reach) for j in hits})
    greenery = _closed(_circles(xy[ids], r[ids])) if ids else None
    return _belt_width(mid, base.normal[near], greenery, base.sides[near])


def _sp276(low: float, high: float) -> str:
    top = high - 1 if math.isfinite(high) else NOISE_RAY_M
    return f"{decimal(SP276_DBA_PER_M * low)}-{decimal(SP276_DBA_PER_M * top)}"


_SIDE_PROBE_M = 1.5  # материал по сторонам борта берётся на этом расстоянии


def _green_sides(mid: np.ndarray, normal: np.ndarray, surface: SurfaceMap | None) -> np.ndarray:
    """В какую сторону мерить полосу: +1, -1, 0 - обе (карты нет), nan - борт не в счёт.

    Шумозащита нужна у борта проезда: с одной стороны покрытие, с другой - грунт. Борт между
    двумя газонами (бордюр в сквере) и между двумя покрытиями не в счёт.
    """
    if surface is None:
        return np.zeros(len(mid))
    left = surface.material(shapely.points(mid + normal * _SIDE_PROBE_M)) == int(Material.PAVED)
    right = surface.material(shapely.points(mid - normal * _SIDE_PROBE_M)) == int(Material.PAVED)
    return np.where(left & ~right, -1.0, np.where(right & ~left, 1.0, np.nan))


def _belt_width(
    mid: np.ndarray, normal: np.ndarray, greenery: BaseGeometry | None, sides: np.ndarray
) -> np.ndarray:
    """Ширина полосы зелени от борта в сторону грунта (или большая из двух), 0 - полосы нет."""
    width = np.zeros(len(mid))
    if greenery is None or not len(mid):
        return width
    t = np.arange(0.0, NOISE_RAY_M + 1e-9, _RAY_STEP_M)
    near = int(_START_M / _RAY_STEP_M) + 1
    cols = np.arange(len(t))
    for side in (1.0, -1.0):
        wanted = (sides == 0) | (sides == side)
        if not wanted.any():
            continue
        points = mid[:, None, :] + side * normal[:, None, :] * t[None, :, None]
        inside = shapely.contains_xy(greenery, points[..., 0], points[..., 1])
        valid = inside[:, :near].any(axis=1)
        start = np.argmax(inside[:, :near], axis=1)
        blocked = ~inside & (cols[None, :] >= start[:, None])
        end = np.where(blocked.any(axis=1), np.argmax(blocked, axis=1), len(t))
        width = np.maximum(width, np.where(valid & wanted, (end - start) * _RAY_STEP_M, 0.0))
    return width


def _kinds(plan: Plan, params: PlanParams) -> tuple[PlantingKind, ...]:
    groups: dict[str, list[str]] = {}
    places: dict[str, Counter[str]] = {}
    for p in plan.placements:
        key = next((_BY_LABEL[n] for n in p.notes if n in _BY_LABEL), "other")
        groups.setdefault(key, []).append(p.planting_type.value)
        places.setdefault(key, Counter())[p.place or "unknown"] += 1
    kinds = []
    for key, title, basis, step in _KINDS:
        types = groups.get(key)
        if not types:
            continue
        kinds.append(
            PlantingKind(
                key=key,
                title=title,
                planting_type=Counter(types).most_common(1)[0][0],
                count=len(types),
                basis=basis,
                length_m=round(len(types) * float(getattr(params, step)), 1) if step else None,
                places=dict(places[key]),
            )
        )
    if groups.get("other"):
        types = groups["other"]
        kinds.append(
            PlantingKind(
                "other", "Прочие посадки", Counter(types).most_common(1)[0][0], len(types), ""
            )
        )
    for kind, key, title in (
        (LawnKind.KEPT, "lawn_kept", "Газон сохраняемый и восстанавливаемый"),
        (LawnKind.NEW, "lawn_new", "Газон устраиваемый"),
    ):
        lawns = [g for g in plan.lawns if g.kind is kind]
        if lawns:
            kinds.append(
                PlantingKind(
                    key,
                    title,
                    "lawn",
                    len(lawns),
                    _LAWN_BASIS,
                    area_m2=round(sum(g.area_m2 for g in lawns), 1),
                )
            )
    return tuple(kinds)


def _notes(site: Site) -> tuple[str, ...]:
    stock = site.stock
    notes = []
    if stock.marks:
        notes.append(
            f"Существующие кроны - круги {decimal(2 * stock.crown_radius)} м вокруг стволов "
            "(параметр existing_crown_m): знак дерева в чертеже - кружок, а не крона."
        )
    if len(stock.strips_xy):
        notes.append(
            f"Полосы деревьев подосновы ({len(stock.strips_xy)} точек знака) учтены кронами, "
            "но не в счёте деревьев."
        )
    return tuple(notes)


def _length(segments: np.ndarray) -> float:
    if not len(segments):
        return 0.0
    return float(np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1).sum())


__all__ = ["NOISE_STEP_M", "SP276_DBA_PER_M", "clear_caches", "street_effect"]
