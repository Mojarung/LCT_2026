"""Слагаемые индекса качества v3 и точная поправка каждого на удаление любой посадки.

v3 (docs/plans/2026-09-26-index-v3-design.md): слагаемое не падает, когда в план добавляется
посадка, прошедшая нормы. Меры-количества считаются к целевому числу посадок участка (МГСН
1.02-02, табл. В.1: 150 деревьев и 600 кустарников на 1 км, деревьев - не больше вместимости
мест, прошедших нормы), а не средним по плану: дерево чуть хуже среднего индекс не снижает,
оно просто добавляет меньше. Выше цели слагаемое насыщено - перебор не штрафуется, но и
баллов не даёт (заказчик: «лучший вариант не самый плотный»).

Каждая функция возвращает оценку от 0 до 1 и массив deltas: насколько оценка упадёт, если
убрать посадку i (при тех же параметрах). Считается это не пересчётом плана N раз, а локально -
сумма без посадки, уникальная площадь кроны, ряд без посадки. Совпадение с прямым пересчётом
проверяет tests/test_quality.py.

Если после удаления слагаемое перестаёт быть определённым, undefined_without помечает такую
посадку. Сборщик индекса перераспределяет веса так же, как при полном пересчёте.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.spatial import KDTree

from green.application.barriers import BARRIER_NOTE
from green.application.explain import OBJECT_LABELS
from green.application.places import category_of
from green.application.quality.coverage import FixedCrowns, fixed_crowns, measure_crowns
from green.application.quality.site import WIDE_STREET_M, site_length
from green.application.wording import counted, decimal, decimal_g
from green.domain.norms import PlantingType
from green.domain.planting import CheckOutcome

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray

    from green.application.params import PlanParams
    from green.application.quality.site import Site
    from green.domain.planting import Placement, Rejection

ROW_TOLERANCE = 0.05  # допуск разбивки к вилке шага ряда
SHRUB_ROW_SPACING_M = (0.3, 1.0)  # 743-ПП, табл. 3.6.2: кустарники в ряду 0,3-0,4 и 0,5-1 м
# МГСН 1.02-02, табл. В.6: рекомендован - 1, с ограничением - 0,5, не рекомендован - 0. Вид,
# о котором таблица молчит, засчитывается половиной: акт его не отвергает, но и не советует.
_CATEGORY = {"plus": 1.0, "limited": 0.5, "minus": 0.0}
CATEGORY_SILENT = 0.5
_CATEGORY_WHERE = {
    "streets": "улиц",
    "yards": "дворов",
    "parks": "парков",
    "squares": "скверов",
    "special": "специальных посадок",
}
_MONTHS_IN = (
    "январе",
    "феврале",
    "марте",
    "апреле",
    "мае",
    "июне",
    "июле",
    "августе",
    "сентябре",
    "октябре",
    "ноябре",
    "декабре",
)
_CIRCLE_SEGMENTS = 8
_MIN_UNIQUE_M2 = 1.0
# Главная порода деревьев выше этой доли - замечание в разнообразии: в принятых проектах
# медиана 40%, половина - предел практики (docs/notes/34-designer-practice.md).
TOP_SHARE_PRACTICE = 0.5
_HALF = 0.5


@dataclass(slots=True)
class TermResult:
    score: float | None
    note: str
    deltas: NDArray[np.float64]
    details: list[str]
    measure: dict[str, float] = field(default_factory=dict)
    undefined_without: NDArray[np.bool_] | None = None


@dataclass(frozen=True, slots=True)
class Layout:
    """Посадки плана в виде массивов: координаты, тип, радиус кроны."""

    placements: Sequence[Placement]
    xy: NDArray[np.float64]
    is_tree: NDArray[np.bool_]
    is_shrub: NDArray[np.bool_]
    # Радиус взрослой кроны: тень, пылезащита и ярус под кроной - функции выросшего дерева.
    # Если взрослая крона в каталоге не задана, берётся крона через 10 лет.
    radius: NDArray[np.float64]

    @classmethod
    def of(cls, placements: Sequence[Placement]) -> Layout:
        xy = np.array([(p.x, p.y) for p in placements], dtype=np.float64).reshape(-1, 2)
        return cls(
            placements=placements,
            xy=xy,
            is_tree=np.array([p.planting_type is PlantingType.TREE for p in placements], bool),
            is_shrub=np.array([p.planting_type is PlantingType.SHRUB for p in placements], bool),
            radius=np.array([_crown(p) / 2 for p in placements], dtype=np.float64).reshape(-1),
        )

    @property
    def size(self) -> int:
        return len(self.placements)

    def empty(self, note: str) -> TermResult:
        return TermResult(None, note, np.zeros(self.size), [""] * self.size)


def _crown(placement: Placement) -> float:
    species = placement.species
    return max(species.crown_mature_m or species.crown_diameter_m, 0.0)


# --- Цели участка --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Targets:
    """Целевые числа посадок участка: к ним меряются слагаемые-количества.

    Свойство участка, а не плана: одинаковы для всех вариантов одной улицы, поэтому варианты
    сравниваются честно, а добавленная посадка не сдвигает собственную цель.
    """

    length_m: float
    trees: float
    shrubs: float
    # 150 деревьев на 1 км (МГСН 1.02-02, табл. В.1) до поправки на вместимость.
    trees_norm: float
    # Сколько деревьев встаёт с шагом 5 м на места, прошедшие нормы (размещение считает её
    # по всем проверенным кандидатам, портфель берёт наибольшую по вариантам).
    capacity: float | None
    # Длина улицы задана из пояснительной записки проекта, а не измерена по оси границы.
    from_note: bool

    def of(self, tree: bool) -> float:  # noqa: FBT001 - группа посадок: деревья или кустарники
        return self.trees if tree else self.shrubs

    @property
    def capped(self) -> bool:
        return self.capacity is not None and self.trees < self.trees_norm


def targets_of(site: Site, params: PlanParams, capacity: float | None) -> Targets | None:
    """Цели участка; None - длина улицы неизвестна (нет границы работ и не задана длина)."""
    length = site_length(site.boundary, params)
    if not length:
        return None
    km = length / 1000
    trees_norm = params.density_trees_per_km[0] * km
    trees = trees_norm
    if params.density_admissible and capacity is not None:
        # МГСН 1.02-02, табл. В.1, сноска: «на 1 км при условии допустимости насаждений».
        trees = min(trees, capacity)
    return Targets(
        length_m=length,
        trees=max(trees, 1.0),
        shrubs=max(params.density_shrubs_per_km[0] * km, 1.0),
        trees_norm=trees_norm,
        capacity=capacity,
        from_note=bool(params.street_length_m),
    )


def _sums(
    layout: Layout,
    values: NDArray[np.float64],
    targets: Targets | None,
    counted: NDArray[np.bool_] | None = None,
) -> tuple[float, NDArray[np.float64], tuple[float, float]]:
    """Половина за деревья, половина за кустарники: min(1, сумма группы / цель группы).

    Возвращает оценку, её убыль от удаления каждой посадки и суммы по группам. Без цели
    (длина улицы неизвестна) - среднее по учтённым посадкам: слагаемое показывает качество
    посадок, а индекс без границы работ и так не выставляется, поэтому убыль не считается.
    """
    counted = np.ones(layout.size, dtype=bool) if counted is None else counted
    tree_sum = float(values[layout.is_tree].sum())
    shrub_sum = float(values[layout.is_shrub].sum())
    deltas = np.zeros(layout.size)
    if targets is None:
        mask = counted & (layout.is_tree | layout.is_shrub)
        score = float(values[mask].mean()) if mask.any() else 0.0
        return score, deltas, (tree_sum, shrub_sum)
    score = 0.0
    for mask, total, target in (
        (layout.is_tree, tree_sum, targets.trees),
        (layout.is_shrub, shrub_sum, targets.shrubs),
    ):
        part = min(1.0, total / target)
        score += _HALF * part
        deltas[mask] = _HALF * (part - np.minimum(1.0, (total - values[mask]) / target))
    return score, deltas, (tree_sum, shrub_sum)


# --- Плотность ---------------------------------------------------------------------------


def density(layout: Layout, site: Site, targets: Targets | None) -> TermResult:
    """Число деревьев и кустарников против цели участка по МГСН 1.02-02, табл. В.1."""
    if targets is None:
        return layout.empty("длина улицы не определена: в чертеже нет границы работ")
    score, deltas, (trees, shrubs) = _sums(layout, np.ones(layout.size), targets)
    km = targets.length_m / 1000
    tree_note = _count_phrase("деревьев", trees, targets.trees)
    shrub_note = _count_phrase("кустарников", shrubs, targets.shrubs)
    details = [
        tree_note if t else shrub_note if s else ""
        for t, s in zip(layout.is_tree.tolist(), layout.is_shrub.tolist(), strict=True)
    ]
    where = "по записке проекта" if targets.from_note else "по оси границы работ"
    note = (
        f"{trees:.0f} деревьев и {shrubs:.0f} кустарников - {trees / km:.0f} и {shrubs / km:.0f} "
        f"на 1 км ({targets.length_m:.0f} м {where}); цель - {targets.trees:.0f} деревьев и "
        f"{targets.shrubs:.0f} кустарников"
    )
    if targets.capped:
        note += (
            f"; деревьев в цели не больше, чем встаёт с шагом 5 м на места, прошедшие нормы "
            f"({targets.capacity:.0f} при {targets.trees_norm:.0f} по В.1)"
        )
    width = site.area_m2 / targets.length_m if site.boundary is not None else 0.0
    if width > WIDE_STREET_M:
        note += (
            "; граница шире улицы - в неё попали дворы или площади, число на 1 км здесь - "
            "оценка сверху"
        )
    measure = {
        "street_length_m": round(targets.length_m, 1),
        "mean_width_m": round(width, 1),
        "trees_per_km": round(trees / km, 1),
        "shrubs_per_km": round(shrubs / km, 1),
        "target_trees": round(targets.trees, 1),
        "target_shrubs": round(targets.shrubs, 1),
    }
    if targets.capacity is not None:
        measure["capacity_trees"] = round(targets.capacity, 1)
    return TermResult(score, note, deltas, details, measure)


def _count_phrase(what: str, count: float, target: float) -> str:
    if count > target:
        return ""
    return (
        f"{what} в плане {count:.0f} при цели {target:.0f} (МГСН 1.02-02, табл. В.1): "
        "каждое на счету"
    )


# --- Ярусность ---------------------------------------------------------------------------


def tiers(layout: Layout, site: Site, targets: Targets | None) -> TermResult:
    """Деревья с кустарником под кроной против цели по деревьям (МГСН 1.02-02, п. 4.2.9.2).

    Существующее дерево, под крону которого план посадил кустарник, - тоже второй ярус,
    созданный планом; дерево, у которого кустарник уже был, в счёт не идёт.
    """
    trees = np.flatnonzero(layout.is_tree)
    covering = _under_crowns(layout, trees)
    existing = _under_existing(layout, site)
    covered = sum(1 for i in trees.tolist() if covering.get(i)) + len(existing)
    goal = targets.trees if targets is not None else float(max(len(trees), 1))
    score = min(1.0, covered / goal)
    deltas = np.zeros(layout.size)
    details = [""] * layout.size
    groups = [covering[i] for i in trees.tolist() if covering.get(i)]
    for i in trees.tolist():
        if covering.get(i):
            deltas[i] = score - min(1.0, (covered - 1) / goal)
            details[i] = "под кроной есть кустарник: второй ярус"
    sole, under = _shrub_tallies([*groups, *existing])
    for s, count in sole.items():
        deltas[s] = score - min(1.0, (covered - count) / goal)
    for s, count in under.items():
        details[s] = f"нижний ярус под кронами деревьев: {count}"
    if targets is None:
        deltas[:] = 0.0
    note = f"деревьев с кустарником под кроной: {covered} из {len(trees) + site.stock.trees}"
    if existing:
        note += f", из них существующих {len(existing)}"
    if targets is not None:
        note += f", цель - {targets.trees:.0f}"
    measure = {
        "trees": len(trees),
        "covered": covered,
        "goal": round(goal, 1),
        "existing": len(existing),
    }
    return TermResult(score, note, deltas, details, measure)


def _shrub_tallies(groups: list[list[int]]) -> tuple[Counter[int], Counter[int]]:
    """Сколько деревьев держится только на этом кусте (sole) и под скольким он стоит (under)."""
    sole: Counter[int] = Counter()
    under: Counter[int] = Counter()
    for shrubs in groups:
        if len(shrubs) == 1:
            sole[shrubs[0]] += 1
        for s in shrubs:
            under[s] += 1
    return sole, under


def _under_existing(layout: Layout, site: Site) -> list[list[int]]:
    """Новые кусты под кроной каждого существующего дерева в границе без своего куста."""
    stock = site.stock
    shrub_index = np.flatnonzero(layout.is_shrub)
    if not len(shrub_index) or not stock.crown_inside.any():
        return []
    trunks = stock.crown_xy[stock.crown_inside]
    tree = KDTree(layout.xy[shrub_index])
    own = KDTree(stock.shrubs_xy) if len(stock.shrubs_xy) else None
    result = []
    for xy in trunks:
        if own is not None and own.query_ball_point(xy, stock.crown_radius):
            continue
        hits = tree.query_ball_point(xy, stock.crown_radius)
        if hits:
            result.append([int(shrub_index[h]) for h in hits])
    return result


def _under_crowns(layout: Layout, trees: NDArray[np.intp]) -> dict[int, list[int]]:
    """Кустарники под взрослой кроной каждого дерева."""
    shrub_index = np.flatnonzero(layout.is_shrub)
    if not len(shrub_index) or not len(trees):
        return {}
    tree = KDTree(layout.xy[shrub_index])
    return {
        i: [int(shrub_index[h]) for h in tree.query_ball_point(layout.xy[i], layout.radius[i])]
        for i in trees.tolist()
    }


# --- Ряды: один вид и ровный шаг --------------------------------------------------------


def rows(
    layout: Layout, params: PlanParams, targets: Targets | None, *, exact: bool = True
) -> TermResult:
    """Посадки рядов, которые держат ряд: сосед того же вида на шаге нормы.

    743-ПП, табл. 3.6.2: однорядная посадка деревьев 5-6 м, кустарников 0,3-1 м. Посадка с
    чужим видом или без соседа на шаге нормы в счёт не идёт, но и не отнимает: разрыв ряда
    у въезда или колодца - условие места, а не ошибка плана.
    """
    members: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(layout.placements):
        info = p.assortment
        if info is not None and info.structure_kind == "row" and info.structure_id:
            members[info.structure_id].append(i)
    groups = [ids for ids in members.values() if len(ids) >= 2]  # noqa: PLR2004 - ряд
    holds = np.zeros(layout.size, dtype=np.float64)
    bands = [_band(layout, ids, params) for ids in groups]
    for ids, band in zip(groups, bands, strict=True):
        holds[ids] = _holders(layout, ids, band)
    score, _, (tree_rows, shrub_rows) = _sums(layout, holds, targets)
    deltas = np.zeros(layout.size)
    details = [""] * layout.size
    if targets is not None and exact:
        for ids, band in zip(groups, bands, strict=True):
            for i in ids:
                # Ряд без посадки: её место пустеет, соседи сходятся, ряд из одной - не ряд.
                others = [j for j in ids if j != i]
                rest = holds.copy()
                rest[ids] = 0.0
                if len(others) >= 2:  # noqa: PLR2004 - ряд
                    rest[others] = _holders(layout, others, band)
                change = holds - rest
                deltas[i] = score - _row_score(
                    tree_rows - float(change[layout.is_tree].sum()),
                    shrub_rows - float(change[layout.is_shrub].sum()),
                    targets,
                )
    for ids, band in zip(groups, bands, strict=True):
        _row_details(layout, ids, band, _fork(layout, ids, params), details)
    rows_count = len(groups)
    total = sum(len(ids) for ids in groups)
    note = (
        f"{counted(rows_count, 'ряд', 'ряда', 'рядов')}, "
        f"{counted(total, 'посадка', 'посадки', 'посадок')}; "
        "держат ряд (сосед того же вида на шаге нормы): "
    )
    note += f"{int(holds.sum())}"
    if targets is not None:
        note += (
            f"; к цели - деревьев {tree_rows:.0f} из {targets.trees:.0f}, кустарников "
            f"{shrub_rows:.0f} из {targets.shrubs:.0f}"
        )
    measure = {"rows": rows_count, "members": total, "holding": int(holds.sum())}
    return TermResult(score, note, deltas, details, measure)


def _row_score(tree_rows: float, shrub_rows: float, targets: Targets) -> float:
    return _HALF * min(1.0, tree_rows / targets.trees) + _HALF * min(
        1.0, shrub_rows / targets.shrubs
    )


def _fork(layout: Layout, ids: list[int], params: PlanParams) -> tuple[float, float]:
    # Ряд кустарника меряется своей вилкой: 743-ПП, табл. 3.6.2 - высоких 0,5-1 м, средних
    # и низких 0,3-0,4 м.
    return SHRUB_ROW_SPACING_M if layout.is_shrub[ids].all() else params.row_spacing_m


def _band(layout: Layout, ids: list[int], params: PlanParams) -> tuple[float, float]:
    low, high = _fork(layout, ids, params)
    return (low * (1 - ROW_TOLERANCE), high * (1 + ROW_TOLERANCE))


def _row_order(layout: Layout, ids: list[int]) -> list[int]:
    points = layout.xy[ids]
    centered = points - points.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    order = np.argsort(centered @ vt[0], kind="stable")
    return [ids[k] for k in order.tolist()]


def _holders(layout: Layout, ids: list[int], band: tuple[float, float]) -> NDArray[np.float64]:
    """1 у посадки ряда (в порядке ids), которая держит ряд: сосед того же вида на шаге нормы.

    Правило локальное: «вид ряда» по большинству перескакивал бы при равенстве счёта, и
    добавленная посадка меняла бы оценку чужих. Здесь посадка держит ряд своим соседством.
    """
    ordered = _row_order(layout, ids)
    steps = np.hypot(*np.diff(layout.xy[ordered], axis=0).T)
    codes = [layout.placements[i].species.code for i in ordered]
    same = np.array([a == b for a, b in pairwise(codes)], dtype=bool)
    good = (steps >= band[0]) & (steps <= band[1]) & same
    near = np.zeros(len(ordered), dtype=bool)
    near[:-1] |= good
    near[1:] |= good
    result = dict(zip(ordered, near.astype(np.float64).tolist(), strict=True))
    return np.array([result[i] for i in ids], dtype=np.float64)


def _row_details(
    layout: Layout,
    ids: list[int],
    band: tuple[float, float],
    fork_m: tuple[float, float],
    details: list[str],
) -> None:
    ordered = _row_order(layout, ids)
    steps = np.hypot(*np.diff(layout.xy[ordered], axis=0).T).tolist()
    codes = [layout.placements[i].species.code for i in ordered]
    for position, i in enumerate(ordered):
        near = [k for k in (position - 1, position) if 0 <= k < len(steps)]
        shown = " и ".join(f"{steps[k]:.1f}" for k in near).replace(".", ",")
        good = any(band[0] <= steps[k] <= band[1] for k in near)
        verdict = "держит шаг ряда" if good else "шаг ряда вне нормы"
        fork = "-".join(decimal_g(value) for value in fork_m)
        text = (
            f"{verdict}: {position + 1}-я в ряду из {len(ordered)}, шаг {shown} м при норме "
            f"{fork} м (743-ПП, табл. 3.6.2)"
        )
        neighbours = [codes[k + (1 if k == position else 0)] for k in near]
        if neighbours and codes[position] not in neighbours:
            text += "; вид отличается от соседей по ряду"
        details[i] = text


# --- Разнообразие -------------------------------------------------------------------------


def diversity(layout: Layout, params: PlanParams, targets: Targets | None) -> TermResult:
    """Видов деревьев и кустарников против цели 5 на группу (медиана принятых проектов).

    Вид засчитывается полностью, когда в нём не меньше diversity_species_share от цели группы
    (при цели 150 деревьев - 15 деревьев), меньше - долей: три посадки редкого вида рядом со
    150 липами - ещё не разнообразие. Мера не падает от добавления посадки: главная порода с
    большой долей не отнимает баллов, их не добирают остальные виды (docs/notes/34).
    """
    placements = layout.placements
    target = params.diversity_target
    groups = []
    for mask, tree in ((layout.is_tree, True), (layout.is_shrub, False)):
        members = np.flatnonzero(mask).tolist()
        counts = Counter(placements[i].species.code for i in members)
        goal = targets.of(tree) if targets is not None else float(max(len(members), 1))
        unit = max(1.0, params.diversity_species_share * goal)
        credit = {code: min(1.0, count / unit) for code, count in counts.items()}
        richness = sum(credit.values())
        groups.append((members, counts, unit, credit, richness))
    score = sum(_HALF * min(1.0, richness / target) for *_, richness in groups)
    deltas = np.zeros(layout.size)
    for members, counts, unit, credit, richness in groups:
        part = min(1.0, richness / target)
        for i in members:
            code = placements[i].species.code
            drop = credit[code] - min(1.0, (counts[code] - 1) / unit)
            deltas[i] = _HALF * (part - min(1.0, (richness - drop) / target))
    if targets is None:
        deltas[:] = 0.0
    tallies = _tallies(layout)
    details = [_diversity_phrase(layout, i, tallies) for i in range(layout.size)]
    (tree_members, tree_counts, _, _, tree_rich), (_, shrub_counts, _, _, shrub_rich) = groups
    top = max(tree_counts.values(), default=0) / len(tree_members) if tree_members else 0.0
    note = (
        f"деревьев {len(tree_counts)} видов (засчитано {decimal(tree_rich)}), кустарников "
        f"{len(shrub_counts)} видов (засчитано {decimal(shrub_rich)}) при цели {target} на группу"
    )
    if tree_members:
        note += f"; главная порода деревьев - {top:.0%}"
        if top > TOP_SHARE_PRACTICE:
            note += " - выше практики принятых проектов (медиана 40%, docs/notes/34)"
    measure = {
        "species_trees": len(tree_counts),
        "species_shrubs": len(shrub_counts),
        "richness_trees": round(tree_rich, 3),
        "richness_shrubs": round(shrub_rich, 3),
        "top_share_trees": round(top, 4),
        "target": target,
    }
    return TermResult(score, note, deltas, details, measure)


_Tally = tuple[Counter[str], Counter[str], Counter[str]]


def _tallies(layout: Layout) -> dict[bool, _Tally]:
    """Счёт семейств, родов и видов отдельно у деревьев и у кустарников."""
    result: dict[bool, _Tally] = {}
    for tree, mask in ((True, layout.is_tree), (False, layout.is_shrub)):
        species = [layout.placements[j].species for j in np.flatnonzero(mask).tolist()]
        result[tree] = (
            Counter(s.family for s in species if s.family),
            Counter(s.genus for s in species if s.genus),
            Counter(s.code for s in species),
        )
    return result


def _diversity_phrase(layout: Layout, i: int, tallies: dict[bool, _Tally]) -> str:
    species = layout.placements[i].species
    if not (layout.is_tree[i] or layout.is_shrub[i]):
        return ""
    families, genera, codes = tallies[bool(layout.is_tree[i])]
    if species.family and families[species.family] == 1:
        return f"единственный представитель семейства {species.family} в плане"
    if species.genus and genera[species.genus] == 1:
        return f"единственный представитель рода {species.genus.capitalize()} в плане"
    if codes[species.code] == 1:
        return "единственная посадка своего вида в плане"
    return ""


# --- Пригодность, категория, запас: суммы по посадкам к цели -----------------------------


def fit(layout: Layout, params: PlanParams, targets: Targets | None) -> TermResult:
    """Пригодность вида месту (оценка подбора из семи факторов) за вычетом поправки за условие.

    Поправка та же, что в подборе (PlanParams.condition_penalty, assortment._obligation):
    посадка на условии (барьер, мужские клоны, контроль вида группы III) и слабый аллерген
    743-ПП не запрещает, но это обязательство на годы. Посадка с поправкой добавляет меньше,
    но не отнимает: отдельного штрафа, который мог бы перевесить посадку, нет.
    """
    percents = [
        p.assortment.percent if p.assortment is not None else None for p in layout.placements
    ]
    counted = np.array([value is not None for value in percents], dtype=bool)
    if not counted.any():
        return layout.empty("виды не подбирались: оценки пригодности нет")
    penalty = params.condition_penalty
    obligations = [obligation(p) for p in layout.placements]
    values = np.array(
        [
            0.0 if percent is None else max(0.0, percent / 100 - penalty * len(owed))
            for percent, owed in zip(percents, obligations, strict=True)
        ],
        dtype=np.float64,
    )
    score, deltas, (trees, shrubs) = _sums(layout, values, targets, counted)
    details = []
    for percent, owed, value in zip(percents, obligations, values.tolist(), strict=True):
        if percent is None:
            details.append("")
        elif owed:
            details.append(
                f"пригодность вида месту {percent}%, с поправкой за {', '.join(owed)} - {value:.0%}"
            )
        else:
            details.append(f"пригодность вида месту {percent}%")
    mean = float(values[counted].mean())
    note = f"средняя пригодность вида месту {mean:.0%}"
    if targets is not None:
        note += (
            f"; сумма к цели: деревья {trees:.0f} из {targets.trees:.0f}, кустарники "
            f"{shrubs:.0f} из {targets.shrubs:.0f}"
        )
    undefined = counted & (counted.sum() == 1)
    return TermResult(score, note, deltas, details, {"mean": round(mean, 4)}, undefined)


def obligation(placement: Placement) -> list[str]:
    """Обязательства посадки: условие (барьер, клоны, контроль вида) и слабый аллерген."""
    owed = []
    if conditional(placement):
        owed.append("условие посадки")
    if placement.species.allergen == 1:
        owed.append("слабый аллерген")
    return owed


def category(layout: Layout, params: PlanParams, targets: Targets | None) -> TermResult:
    """Рекомендация вида для категории территории по МГСН 1.02-02, табл. В.6, к цели участка.

    Вид вне таблицы - половина балла, как «с ограничением»: акт о нём молчит. Сверх этого он
    слабее на 0,25 в факторе «категория» оценки пригодности - это пригодность, а здесь -
    рекомендация акта.
    """
    # Категория - по месту посадки (application/places): у двора и улицы она своя; место
    # не определено - категория профиля.
    keys = [category_of(p.place, params.planting_category) for p in layout.placements]
    marks = [p.species.categories.get(k, "") for p, k in zip(layout.placements, keys, strict=True)]
    values = np.array([_CATEGORY.get(mark, CATEGORY_SILENT) for mark in marks], dtype=np.float64)
    score, deltas, _ = _sums(layout, values, targets)
    tally = Counter(mark if mark in _CATEGORY else "silent" for mark in marks)
    details = [
        _category_phrase(mark, _CATEGORY_WHERE.get(k, k))
        for mark, k in zip(marks, keys, strict=True)
    ]
    wheres = sorted({_CATEGORY_WHERE.get(k, k) for k in keys}) or [
        _CATEGORY_WHERE.get(params.planting_category, params.planting_category)
    ]
    note = (
        f"для {' и '.join(wheres)}: рекомендованных посадок {tally['plus']}, с ограничением "
        f"{tally['limited']}, не рекомендованных {tally['minus']}, вне табл. В.6 "
        f"{tally['silent']} (засчитаны половиной)"
    )
    measure = {name: float(tally[name]) for name in ("plus", "limited", "minus", "silent")}
    return TermResult(score, note, deltas, details, measure)


def _category_phrase(mark: str, where: str) -> str:
    return {
        "plus": f"рекомендован для {where} (МГСН 1.02-02, табл. В.6)",
        "limited": f"для {where} с ограничением (МГСН 1.02-02, табл. В.6)",
        "minus": f"не рекомендован для {where} (МГСН 1.02-02, табл. В.6)",
    }.get(mark, "в табл. В.6 МГСН 1.02-02 вида нет")


def _m(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def tightest(placement: Placement) -> tuple[float, str] | None:
    """Запас до самой тесной нормы до подземной сети, м (измерено минус норма), и её описание.

    Только сети: СП 317.1325800.2017, п. 5.3.5.3 говорит о «скрытых точках подземных
    сооружений». Борт, стену и ограду при посадке меряют от настоящих, их положение на плане
    не догадка.
    """
    best: tuple[float, str] | None = None
    for check in placement.checks:
        if check.measured_m is None or not check.threshold_m or check.threshold_m <= 0:
            continue
        if check.object_class is None or not check.object_class.is_utility:
            continue
        # Мягкая норма «на согласование» тоже в счёт: запас по ней отрицательный, балл ноль.
        if check.outcome is CheckOutcome.NO_DATA:
            continue
        slack = check.measured_m - check.threshold_m
        if best is None or slack < best[0]:
            # Сеть называется по имени, правило уже стоит в блоке нормы той же панели.
            target = OBJECT_LABELS.get(check.object_class, "сети")
            text = f"до {target} {_m(check.measured_m)} м при норме {_m(check.threshold_m)} м"
            best = (slack, text)
    return best


def margin(layout: Layout, params: PlanParams, targets: Targets | None) -> TermResult:
    """Посадки с запасом до подземных сетей: полный балл с margin_target_m сверх нормы.

    СП 317.1325800.2017, п. 5.3.5.3: на плане 1:500 положение подземных сетей может
    расходиться с натурой до 0,5 м. Посадка ровно на норме по чертежу на месте может оказаться
    ближе нормы: она засчитывается долей запаса. Посадка без сети рядом - полный балл.
    """
    goal = params.margin_target_m
    found = [tightest(p) for p in layout.placements]
    values = np.array(
        [1.0 if item is None else min(1.0, max(0.0, item[0] / goal)) for item in found],
        dtype=np.float64,
    )
    score, deltas, _ = _sums(layout, values, targets)
    # Запас больше цели слагаемое уже насытил: «запас 42 м» - не заслуга посадки, а отсутствие
    # сети рядом, и в причинах ценности он только занимает строку.
    details = [
        "" if item is None or item[0] >= goal else f"запас {_m(item[0])} м сверх нормы: {item[1]}"
        for item in found
    ]
    tight = sum(1 for item in found if item is not None and item[0] < goal)
    note = (
        f"посадок с запасом не меньше {_m(goal)} м сверх нормы до подземных сетей или без сетей "
        f"рядом: {layout.size - tight} из {layout.size}; впритык к норме: {tight}"
    )
    return TermResult(score, note, deltas, details, {"tight": float(tight)})


# --- Тень и пылезащита --------------------------------------------------------------------


def canopy(
    layout: Layout,
    site: Site,
    params: PlanParams,
    targets: Targets | None,
    *,
    exact: bool = True,
) -> TermResult:
    """Площадь взрослых крон против крон целевого числа деревьев; полный балл с canopy_target.

    Цель - кроны целевого числа деревьев участка с кроной canopy_crown_m (медиана взрослой
    кроны деревьев каталога): так тень меряется в тех же единицах, что плотность, и
    мелкокронный вид даёт меньше, чем крупнокронный (Kenney, van Wassenaer, Satel 2011:
    относительная площадь крон «optimal» с 75% потенциала).
    """
    if site.boundary is None or site.area_m2 <= 0 or targets is None:
        return layout.empty("нет границы работ: не от чего считать тень")
    boundary = site.boundary
    crown = params.canopy_crown_m
    goal = params.canopy_target * targets.trees * math.pi * (crown / 2) ** 2
    trees = np.flatnonzero(layout.is_tree)
    deltas = np.zeros(layout.size)
    details = [""] * layout.size
    # Существующие кроны: тень улицы - их и новых вместе, новая крона поверх существующей
    # ничего не добавляет. Они одинаковы во всех вариантах, выбор решает прирост.
    existing = site.stock.canopy
    existing_m2 = float(existing.area) if existing is not None else 0.0
    if not len(trees):
        return TermResult(
            min(1.0, existing_m2 / goal),
            "деревьев нет" + (f"; существующие кроны {existing_m2:.0f} м²" if existing_m2 else ""),
            deltas,
            details,
            {"m2": round(existing_m2), "goal_m2": goal, "existing_m2": round(existing_m2)},
        )
    circles = shapely.buffer(
        shapely.points(layout.xy[trees]), layout.radius[trees], quad_segs=_CIRCLE_SEGMENTS
    )
    shapely.prepare(boundary)
    planted = shapely.intersection(shapely.union_all(circles), boundary)
    if existing is not None:
        shapely.prepare(existing)
        planted = shapely.union(planted, existing)
    covered = float(planted.area)
    score = min(1.0, covered / goal)
    index = shapely.STRtree(circles)
    for k, i in enumerate(trees.tolist() if exact else ()):
        own = circles[k]
        near = [j for j in index.query(own, predicate="intersects").tolist() if j != k]
        if near:
            own = shapely.difference(own, shapely.union_all(circles[near]))
        if existing is not None and shapely.intersects(existing, own):
            own = shapely.difference(own, existing)
        unique = (
            float(own.area)
            if shapely.contains(boundary, own)
            else float(shapely.intersection(own, boundary).area)
        )
        deltas[i] = score - min(1.0, (covered - unique) / goal)
        if unique >= _MIN_UNIQUE_M2:
            details[i] = (
                f"взрослая крона даёт {unique:.0f} м² тени, которых не даёт больше ни одно дерево"
            )
    note = (
        f"взрослые кроны закрывают {covered:.0f} м²; цель - {params.canopy_target:.0%} крон "
        f"{targets.trees:.0f} деревьев с кроной {decimal(crown)} м (медиана каталога), "
        f"{goal:.0f} м²"
    )
    if existing_m2:
        note += f"; из них существующие кроны {existing_m2:.0f} м²"
    # Сумма кругов крон без перекрытий: отношение m2 / sum_m2 - перекрытие крон этого участка;
    # по нему оценивается тень плана, у которого есть состав, но нет координат (проектировщик).
    total = float(np.sum(math.pi * layout.radius[trees] ** 2))
    measure = {
        "m2": round(covered),
        "goal_m2": round(goal),
        "share": round(covered / goal, 4),
        "sum_m2": round(total),
        "existing_m2": round(existing_m2),
    }
    return TermResult(score, note, deltas, details, measure)


def dust(layout: Layout, site: Site, params: PlanParams) -> TermResult:
    """Доля бортов под кронами, взвешенная газоустойчивостью вида (0-2 -> 0-1)."""
    segments = site.curb_segments
    if not len(segments):
        return layout.empty("бортов в границе работ нет: пылезащиту мерить не по чему")
    total_curb = _length(segments)
    if params.dust_admissible and site.curb_soil is not None:
        # Только борта с грунтом в полосе у борта: там нижнему ярусу есть где встать.
        segments = segments[site.curb_soil]
        if not len(segments):
            return layout.empty("у бортов нет грунта: нижнему ярусу встать негде")
    target = params.dust_target
    # Abhijith et al. 2017: в уличном каньоне кроны над проезжей частью ухудшают воздух у
    # земли, а работает сомкнутый низкий ярус от земли. Кустарник у борта засчитывается целиком,
    # метр только под кроной дерева - с коэффициентом dust_crown_factor.
    layer = np.where(layout.is_shrub, 1.0, params.dust_crown_factor)
    weight = layer * np.array(
        [p.species.gas_tolerance / 2 for p in layout.placements], dtype=np.float64
    )
    # Кустарник закрывает борт, если стоит в полосе у борта (полоса, закрытая для деревьев);
    # дерево - только кроной над бортом. Длина считается точно по отрезкам (coverage.py).
    cover = np.where(layout.is_shrub, np.maximum(layout.radius, params.dust_strip_m), layout.radius)
    # Существующие кроны и кусты тоже закрывают борт: вид неизвестен, газоустойчивость средняя
    # (1 из 2). Вклад новой посадки - только то, чего они не закрывают.
    fixed = _fixed_cover(site, params, segments)
    coverage = measure_crowns(segments, layout.xy, cover, weight, fixed=fixed)
    loss, reach = coverage.loss_m, coverage.reach_m
    total, count = coverage.weighted_m, coverage.length_m
    share = total / count
    score = min(1.0, share / target)
    deltas = score - np.minimum(1.0, (total - loss) / count / target)
    covered = coverage.covered_m
    existing_covered = fixed.covered_m
    details = [
        (
            f"{'нижний ярус у борта' if layout.is_shrub[i] else 'крона над бортом'}: "
            f"{decimal(reach[i])} м, газоустойчивость {p.species.gas_tolerance} из 2"
        )
        if reach[i]
        else ""
        for i, p in enumerate(layout.placements)
    ]
    note = (
        f"под кронами {decimal(covered)} м бортов из {decimal(count)} ({covered / count:.0%}), "
        f"с поправкой на газоустойчивость {share:.0%} при цели {target:.0%}"
    )
    if existing_covered:
        note += f"; существующие кроны и кусты закрывают {decimal(existing_covered)} м"
    measure = {
        "curb_m": count,
        "covered_m": covered,
        "share": round(share, 4),
        "existing_covered_m": existing_covered,
    }
    if count < total_curb - _LENGTH_EPS_M:
        note += f"; в счёт только борта с грунтом рядом, {count:.0f} м из {total_curb:.0f}"
        measure["curb_total_m"] = total_curb
    return TermResult(score, note, deltas, details, measure)


# Газоустойчивость существующего насаждения, вид которого чертёж не называет: средняя, 1 из 2.
EXISTING_GAS_WEIGHT = 0.5


# Существующие кроны одинаковы во всех оценках прогона: их покрытие бортов считается один раз
# на участок (сдвиг слабых мест оценивает сотни пробных планов). Ключ - сами массивы участка:
# запись хранит ссылки на них, поэтому чужой участок с тем же id её не получит.
_FIXED: list[tuple[tuple[tuple[object, ...], tuple[object, ...]], FixedCrowns]] = []
_FIXED_SIZE = 4


def _fixed_cover(site: Site, params: PlanParams, segments: NDArray[np.float64]) -> FixedCrowns:
    arrays = (site.stock, site.curb_segments, site.curb_soil)
    values = (params.dust_strip_m, params.dust_crown_factor, params.dust_admissible)
    for (held, same), fixed in _FIXED:
        if all(a is b for a, b in zip(held, arrays, strict=True)) and same == values:
            return fixed
    fixed = fixed_crowns(segments, *_existing_cover(site, params))
    _FIXED.insert(0, ((arrays, values), fixed))
    del _FIXED[_FIXED_SIZE:]
    return fixed


def _existing_cover(
    site: Site, params: PlanParams
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Существующие кроны и кусты для покрытия бортов: центры, радиусы, веса."""
    crowns, radii = site.stock.crowns()
    shrubs = site.stock.shrubs_xy
    return (
        np.vstack([crowns, shrubs]),
        np.concatenate([radii, np.full(len(shrubs), params.dust_strip_m)]),
        np.concatenate(
            [
                np.full(len(crowns), params.dust_crown_factor * EXISTING_GAS_WEIGHT),
                np.full(len(shrubs), EXISTING_GAS_WEIGHT),
            ]
        ),
    )


# Разница длин бортов меньше этого - округление, а не отсеянные борта без грунта.
_LENGTH_EPS_M = 1e-6


def _length(segments: NDArray[np.float64]) -> float:
    return float(np.linalg.norm(segments[:, 1] - segments[:, 0], axis=1).sum())


# --- Сезонность ---------------------------------------------------------------------------


def season(layout: Layout) -> TermResult:
    """Сколько месяцев из 12 есть декоративные посадки (из каталога видов).

    Считаются все посадки плана, деревья и кустарники вместе, а сводка состава - отдельно
    деревья и отдельно кустарники. Поэтому текст называет, кого он считает, и месяцы без
    декоративных посадок: иначе месяц, который закрыл один куст, спорит с пустым месяцем в
    сводке деревьев.
    """
    months = [sorted(p.species.decor_months) for p in layout.placements]
    base = np.zeros(12)
    for owned in months:
        for month in owned:
            base[month - 1] += 1
    active = int((base > 0).sum())
    score = active / 12
    deltas = np.zeros(layout.size)
    details = [""] * layout.size
    for i, owned in enumerate(months):
        alone = [m for m in owned if base[m - 1] == 1]
        deltas[i] = len(alone) / 12
        if alone:
            where = ", ".join(_MONTHS_IN[m - 1] for m in alone)
            details[i] = f"единственная декоративная посадка в {where}"
    return TermResult(score, _season_note(base), deltas, details, {"months": active})


def _season_note(base: NDArray[np.float64]) -> str:
    who = "деревья и кустарники вместе"
    active = int((base > 0).sum())
    if not active:
        return f"{who}: декоративных посадок нет ни в одном месяце"
    months = "месяце" if active == 1 else "месяцах"
    note = f"{who}: декоративные посадки есть в {active} {months} из 12"
    bare = [_MONTHS_IN[m] for m in range(12) if base[m] == 0]
    return f"{note}; нет в {', '.join(bare)}" if bare else note


# --- Штрафы и отметки ---------------------------------------------------------------------


def conditional(placement: Placement) -> bool:
    """Посадка допустима только при условии: барьер, мужские клоны, контроль вида группы III."""
    info = placement.assortment
    has_condition = info is not None and any(reason.condition for reason in info.reasons)
    return has_condition or BARRIER_NOTE in placement.notes


def lost_places(rejections: Sequence[Rejection]) -> int:
    """Места, допустимые по нормам, но оставшиеся пустыми (квоты, заданные количества)."""
    return sum(
        1
        for r in rejections
        if r.note and all(check.outcome is not CheckOutcome.FAIL for check in r.blocking)
    )
