"""Слагаемые индекса качества и точная поправка каждого на удаление любой посадки.

Каждая функция возвращает оценку слагаемого от 0 до 1 и массив deltas: насколько оценка
упадёт, если убрать посадку i (при тех же параметрах). Считается это не пересчётом плана N
раз, а локально - сдвиг счётчика вида, уникальная площадь кроны, соседи по ряду. Совпадение с
прямым пересчётом проверяет tests/test_quality.py.

Если после удаления слагаемое перестаёт быть определённым (из ряда в два дерева убрали
одно), его оценка без посадки считается нулём: вес слагаемых при удалении не перераспределяется.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.spatial import KDTree

from green.application.barriers import BARRIER_NOTE
from green.application.placement import MODE_LABELS
from green.application.quality.coverage import measure_crowns
from green.domain.norms import PlantingType
from green.domain.planting import CheckOutcome

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from numpy.typing import NDArray

    from green.application.params import PlanParams
    from green.application.quality.site import Site
    from green.domain.planting import Placement, Rejection

ALLEY_NOTE = MODE_LABELS["alley"]
ROW_TOLERANCE = 0.05  # допуск разбивки к вилке шага ряда
_CATEGORY = {"plus": 1.0, "limited": 0.5, "minus": 0.0}
_CATEGORY_UNKNOWN = 0.25  # вида нет в табл. В.6: как в оценке подбора (assortment/scoring.py)
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
# Шире этого граница работ уже не полоса улицы: в ней дворы или площадь, и «на 1 км улицы»
# теряет смысл. Самый широкий профиль магистральной улицы в Москве - порядка 80 м.
WIDE_STREET_M = 80.0
_MIN_UNIQUE_M2 = 1.0


@dataclass(slots=True)
class TermResult:
    score: float | None
    note: str
    deltas: NDArray[np.float64]
    details: list[str]
    measure: dict[str, float] = field(default_factory=dict)


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


# --- Плотность ---------------------------------------------------------------------------


def fork(value: float, low: float, high: float, *, excess: bool = True) -> float:
    """Трапеция по вилке нормы: ниже - доля от нижней границы, выше - спад к нулю на 3*high.

    Заказчик прямо сказал «лучший вариант не самый плотный», поэтому переплотнение стоит
    баллов. Но В.1 - рекомендуемый максимум, а не запрет, поэтому спад сверху вдвое положе.
    """
    if value < low:
        return max(value, 0.0) / low
    if value <= high or not excess:
        return 1.0
    return max(0.0, 1.0 - (value - high) / (2 * high))


def density(layout: Layout, site: Site, params: PlanParams) -> TermResult:
    length = site.street_length_m
    if not length:
        return layout.empty("длина улицы не определена: в чертеже нет границы работ")
    km = length / 1000
    trees, shrubs = int(layout.is_tree.sum()), int(layout.is_shrub.sum())
    t_low, t_high = params.density_trees_per_km
    s_low, s_high = params.density_shrubs_per_km
    # Если граница шире улицы, в ней дворы, и число посадок на 1 км улицы завышено. Оценка
    # сверху доказывает недосадку, но не перебор: перебор здесь не штрафуется.
    width = site.area_m2 / length
    excess = width <= WIDE_STREET_M

    def score_of(t: int, s: int) -> float:
        return 0.5 * fork(t / km, t_low, t_high, excess=excess) + 0.5 * fork(
            s / km, s_low, s_high, excess=excess
        )

    score = score_of(trees, shrubs)
    tree_drop = score - score_of(trees - 1, shrubs)
    shrub_drop = score - score_of(trees, shrubs - 1)
    deltas = np.where(layout.is_tree, tree_drop, np.where(layout.is_shrub, shrub_drop, 0.0))
    per_km_t, per_km_s = trees / km, shrubs / km
    tree_note = _density_phrase("деревьев", per_km_t, t_low, t_high, excess=excess)
    shrub_note = _density_phrase("кустарников", per_km_s, s_low, s_high, excess=excess)
    details = [
        tree_note if t else shrub_note if s else ""
        for t, s in zip(layout.is_tree.tolist(), layout.is_shrub.tolist(), strict=True)
    ]
    note = (
        f"{per_km_t:.0f} деревьев и {per_km_s:.0f} кустарников на 1 км улицы "
        f"({length:.0f} м по границе работ, средняя ширина {width:.0f} м) при вилке "
        f"{t_low:.0f}-{t_high:.0f} и {s_low:.0f}-{s_high:.0f}"
    )
    if not excess:
        note += (
            "; граница шире улицы - в неё попали дворы или площади, плотность на 1 км здесь "
            "оценка сверху, и перебор не штрафуется"
        )
    measure = {
        "street_length_m": round(length, 1),
        "mean_width_m": round(width, 1),
        "trees_per_km": round(per_km_t, 1),
        "shrubs_per_km": round(per_km_s, 1),
    }
    return TermResult(score, note, deltas, details, measure)


def _density_phrase(
    what: str, per_km: float, low: float, high: float, *, excess: bool = True
) -> str:
    fork_text = f"{low:.0f}-{high:.0f}, МГСН 1.02-02, табл. В.1"
    if per_km < low:
        return (
            f"{what} на улице меньше нормы ({per_km:.0f} на 1 км при {fork_text}): каждое на счету"
        )
    if per_km > high and excess:
        return f"{what} больше рекомендуемого максимума ({per_km:.0f} на 1 км при {fork_text})"
    return ""


# --- Ярусность ---------------------------------------------------------------------------


def tiers(layout: Layout) -> TermResult:
    """Доля деревьев аллеи, под кроной которых есть кустарник (МГСН 1.02-02, п. 4.2.9.2)."""
    alley = [
        i for i, p in enumerate(layout.placements) if layout.is_tree[i] and ALLEY_NOTE in p.notes
    ]
    if not alley:
        return layout.empty("аллеи нет: ярусность под кронами мерить не на чем")
    shrub_index = np.flatnonzero(layout.is_shrub)
    covering: dict[int, list[int]] = {}
    if len(shrub_index):
        tree = KDTree(layout.xy[shrub_index])
        for i in alley:
            hits = tree.query_ball_point(layout.xy[i], layout.radius[i])
            covering[i] = [int(shrub_index[h]) for h in hits]
    total = len(alley)
    covered = sum(1 for i in alley if covering.get(i))
    score = covered / total
    deltas = np.zeros(layout.size)
    details = [""] * layout.size
    sole: Counter[int] = Counter()
    under: Counter[int] = Counter()
    for i in alley:
        shrubs = covering.get(i, [])
        after = (covered - (1 if shrubs else 0)) / (total - 1) if total > 1 else 0.0
        deltas[i] = score - after
        if shrubs:
            details[i] = "под кроной есть кустарник: второй ярус аллеи"
        if len(shrubs) == 1:
            sole[shrubs[0]] += 1
        for s in shrubs:
            under[s] += 1
    for s, count in sole.items():
        deltas[s] = score - (covered - count) / total
    for s, count in under.items():
        details[s] = f"нижний ярус под кронами деревьев аллеи: {count}"
    note = f"под кронами {covered} из {total} деревьев аллеи есть кустарник"
    return TermResult(score, note, deltas, details, {"alley_trees": total, "covered": covered})


# --- Ряды: один вид и ровный шаг --------------------------------------------------------


def rows(layout: Layout, params: PlanParams) -> TermResult:
    """Однородность там, где она нужна: ряд аллеи - один вид и шаг по 743-ПП, табл. 3.6.2."""
    members: dict[str, list[int]] = defaultdict(list)
    for i, p in enumerate(layout.placements):
        info = p.assortment
        if info is not None and info.structure_kind == "row" and info.structure_id:
            members[info.structure_id].append(i)
    groups = {key: ids for key, ids in members.items() if len(ids) >= 2}  # noqa: PLR2004 - ряд
    if not groups:
        return layout.empty("рядов нет: однородность и шаг мерить не на чем")
    low, high = params.row_spacing_m
    band = (low * (1 - ROW_TOLERANCE), high * (1 + ROW_TOLERANCE))

    def score_of(ids: list[int]) -> float:
        return _row_score(layout, ids, band)[0]

    scores = {key: score_of(ids) for key, ids in groups.items()}
    total = sum(len(ids) for ids in groups.values())
    weighted = sum(len(groups[key]) * scores[key] for key in groups)
    score = weighted / total
    deltas = np.zeros(layout.size)
    details = [""] * layout.size
    for key, ids in groups.items():
        rest = weighted - len(ids) * scores[key]
        for i in ids:
            others = [j for j in ids if j != i]
            if len(others) >= 2:  # noqa: PLR2004 - ряд из двух посадок
                after = (rest + len(others) * score_of(others)) / (total - 1)
            else:
                remaining = total - len(ids)
                after = rest / remaining if remaining else 0.0
            deltas[i] = score - after
        _row_details(layout, ids, band, (low, high), details)
    in_band = sum(_row_score(layout, ids, band)[1] for ids in groups.values())
    gaps = sum(len(ids) - 1 for ids in groups.values())
    note = (
        f"{len(groups)} рядов, {total} посадок; шагов в вилке {low:g}-{high:g} м: "
        f"{in_band} из {gaps}"
    )
    return TermResult(score, note, deltas, details, {"rows": len(groups), "gaps_in_band": in_band})


def _row_order(layout: Layout, ids: list[int]) -> list[int]:
    points = layout.xy[ids]
    centered = points - points.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    order = np.argsort(centered @ vt[0], kind="stable")
    return [ids[k] for k in order.tolist()]


def _row_score(layout: Layout, ids: list[int], band: tuple[float, float]) -> tuple[float, int]:
    ordered = _row_order(layout, ids)
    steps = np.hypot(*np.diff(layout.xy[ordered], axis=0).T)
    in_band = int(((steps >= band[0]) & (steps <= band[1])).sum())
    codes = Counter(layout.placements[i].species.code for i in ids)
    dominant = max(codes.values()) / len(ids)
    return dominant * in_band / len(steps), in_band


def _row_details(
    layout: Layout,
    ids: list[int],
    band: tuple[float, float],
    fork_m: tuple[float, float],
    details: list[str],
) -> None:
    ordered = _row_order(layout, ids)
    steps = np.hypot(*np.diff(layout.xy[ordered], axis=0).T).tolist()
    codes = Counter(layout.placements[i].species.code for i in ids)
    main = codes.most_common(1)[0][0]
    for position, i in enumerate(ordered):
        near = [steps[k] for k in (position - 1, position) if 0 <= k < len(steps)]
        shown = " и ".join(f"{step:.1f}" for step in near).replace(".", ",")
        good = all(band[0] <= step <= band[1] for step in near)
        verdict = "держит шаг ряда" if good else "шаг ряда вне нормы"
        text = (
            f"{verdict}: {position + 1}-я в ряду из {len(ordered)}, шаг {shown} м при норме "
            f"{fork_m[0]:g}-{fork_m[1]:g} м (743-ПП, табл. 3.6.2)"
        )
        if layout.placements[i].species.code != main:
            text += "; вид отличается от остального ряда"
        details[i] = text


# --- Разнообразие между структурами ---------------------------------------------------------


def diversity(layout: Layout, params: PlanParams) -> TermResult:
    """Число видов и запас до квот 10-20-30 по плану целиком.

    Цель по числу видов - не больше, чем видов допустимо на этих местах: у борта соль и крона
    оставляют немного видов, и штрафовать улицу за то, что нормы сузили выбор, нечестно.
    Допустимыми считаются выбранные виды и альтернативы, которые подбор предлагал местам.
    """
    if not layout.size:
        return layout.empty("посадок нет")
    placements = layout.placements
    counts = Counter(p.species.code for p in placements)
    admissible = set(counts) | {
        a.code for p in placements if p.assortment is not None for a in p.assortment.alternatives
    }
    target = max(1, min(params.diversity_target, len(admissible)))
    populations = _populations(layout, params)

    def score_of(removed: int | None) -> tuple[float, float, float]:
        tally = counts.copy()
        if removed is not None:
            tally[placements[removed].species.code] -= 1
        n = sum(tally.values())
        richness = min(1.0, _effective(tally.values(), n) / target) if n else 0.0
        fits = [(pop.size_without(removed), pop.fit(removed)) for pop in populations]
        weight = sum(size for size, _ in fits)
        quota = sum(size * fit for size, fit in fits) / weight if weight else 1.0
        return 0.5 * richness + 0.5 * quota, richness, quota

    score, richness, quota = score_of(None)
    cache: dict[tuple[str, bool], float] = {}
    deltas = np.zeros(layout.size)
    for i, p in enumerate(placements):
        key = (p.species.code, bool(layout.is_tree[i]))
        if key not in cache:
            cache[key] = score - score_of(i)[0]
        deltas[i] = cache[key]
    details = [_diversity_phrase(layout, i, populations) for i in range(layout.size)]
    effective = _effective(counts.values(), layout.size)
    quota_text = "соблюдены" if quota >= 1 else f"превышены, выполнение {quota:.2f}"
    note = (
        f"{len(counts)} видов, эффективное число {effective:.1f} при цели {target} "
        f"(допустимо местам видов: {len(admissible)}); квоты вида, рода и семейства {quota_text}"
    )
    measure = {
        "species": len(counts),
        "effective_species": round(effective, 2),
        "target": target,
        "admissible": len(admissible),
        "richness": round(richness, 4),
        "quota_fit": round(quota, 4),
    }
    return TermResult(score, note, deltas, details, measure)


def _effective(values: Iterable[int], n: int) -> float:
    """Эффективное число видов exp(H) по Шеннону: столько равных по численности видов."""
    counts = [v for v in values if v > 0]
    if not n or not counts:
        return 0.0
    return math.exp(-sum((v / n) * math.log(v / n) for v in counts))


@dataclass(slots=True)
class _Population:
    """Деревья или кустарники: у каждой группы свои квоты разнообразия."""

    members: list[int]
    keys: dict[int, tuple[str, str, str]]  # посадка -> (вид, род, семейство)
    quotas: tuple[float, float, float]
    tallies: tuple[Counter[str], Counter[str], Counter[str]]

    @property
    def size(self) -> int:
        return len(self.members)

    def size_without(self, removed: int | None) -> int:
        return self.size - (1 if removed in self.keys else 0)

    def fit(self, removed: int | None) -> float:
        """Выполнение квот: 1 - все доли в пределах, иначе квота / худшая доля."""
        n = self.size_without(removed)
        if n <= 0:
            return 1.0
        worst = 1.0
        for level, (tally, quota) in enumerate(zip(self.tallies, self.quotas, strict=True)):
            local = tally
            if removed in self.keys:
                local = tally.copy()
                local[self.keys[removed][level]] -= 1
            # Один экземпляр вида, рода или семейства квоту не нарушает (как в подборе).
            shares = [count / n for count in local.values() if count >= 2]  # noqa: PLR2004
            top = max(shares, default=0.0)
            if top > quota:
                worst = min(worst, quota / top)
        return worst


def _populations(layout: Layout, params: PlanParams) -> list[_Population]:
    groups = (
        (layout.is_tree, (params.quota_species, params.quota_genus, params.quota_family)),
        (
            layout.is_shrub,
            (params.shrub_quota_species, params.shrub_quota_genus, params.shrub_quota_family),
        ),
    )
    result = []
    for mask, quotas in groups:
        members = np.flatnonzero(mask).tolist()
        keys = {
            i: (
                layout.placements[i].species.code,
                layout.placements[i].species.genus or layout.placements[i].species.code,
                layout.placements[i].species.family or layout.placements[i].species.code,
            )
            for i in members
        }
        tallies = (
            Counter(key[0] for key in keys.values()),
            Counter(key[1] for key in keys.values()),
            Counter(key[2] for key in keys.values()),
        )
        result.append(_Population(members, keys, quotas, tallies))
    return result


def _diversity_phrase(layout: Layout, i: int, populations: list[_Population]) -> str:
    species = layout.placements[i].species
    for population in populations:
        if i not in population.keys:
            continue
        code, genus, family = population.keys[i]
        tally_species, tally_genus, tally_family = population.tallies
        if tally_family[family] == 1 and species.family:
            return f"единственный представитель семейства {species.family} в плане"
        if tally_genus[genus] == 1 and species.genus:
            return f"единственный представитель рода {species.genus.capitalize()} в плане"
        if tally_species[code] == 1:
            return "единственная посадка своего вида в плане"
        share = tally_species[code] / population.size
        if share > population.quotas[0]:
            return f"вид сверх квоты: {share:.0%} посадок при квоте {population.quotas[0]:.0%}"
    return ""


# --- Средние по посадкам: пригодность, категория, запас ------------------------------------


def _mean_term(
    values: list[float | None], note: Callable[[float], str], measure_key: str
) -> tuple[float | None, NDArray[np.float64], str, dict[str, float]]:
    defined = [v for v in values if v is not None]
    deltas = np.zeros(len(values))
    if not defined:
        return None, deltas, "", {}
    total, count = sum(defined), len(defined)
    score = total / count
    for i, value in enumerate(values):
        if value is None:
            continue
        deltas[i] = score - ((total - value) / (count - 1) if count > 1 else 0.0)
    return score, deltas, note(score), {measure_key: round(score, 4)}


def fit(layout: Layout) -> TermResult:
    """Средняя пригодность вида месту: оценка подбора из семи факторов (assortment/scoring)."""
    values: list[float | None] = [
        p.assortment.percent / 100 if p.assortment is not None else None for p in layout.placements
    ]
    score, deltas, note, measure = _mean_term(
        values, lambda s: f"средняя пригодность вида месту {s:.0%}", "mean"
    )
    if score is None:
        return layout.empty("виды не подбирались: оценки пригодности нет")
    details = [
        f"пригодность вида месту {p.assortment.percent}%" if p.assortment is not None else ""
        for p in layout.placements
    ]
    return TermResult(score, note, deltas, details, measure)


def category(layout: Layout, params: PlanParams) -> TermResult:
    """Доля посадок, рекомендованных МГСН 1.02-02, табл. В.6 для категории территории."""
    key = params.planting_category
    where = _CATEGORY_WHERE.get(key, key)
    marks = [p.species.categories.get(key, "") for p in layout.placements]
    values: list[float | None] = [_CATEGORY.get(mark, _CATEGORY_UNKNOWN) for mark in marks]
    score, deltas, _, _ = _mean_term(values, str, "mean")
    if score is None:
        return layout.empty("посадок нет")
    plus = sum(1 for mark in marks if mark == "plus")
    unknown = sum(1 for mark in marks if mark not in _CATEGORY)
    phrases = {
        "plus": f"рекомендован для {where} (МГСН 1.02-02, табл. В.6)",
        "limited": f"для {where} с ограничением (МГСН 1.02-02, табл. В.6)",
        "minus": f"не рекомендован для {where} (МГСН 1.02-02, табл. В.6)",
    }
    details = [phrases.get(mark, "в табл. В.6 МГСН 1.02-02 вида нет") for mark in marks]
    note = (
        f"рекомендованы для {where} {plus} из {len(marks)} посадок; вида нет в табл. В.6: {unknown}"
    )
    measure = {"plus": plus, "unknown": unknown}
    return TermResult(score, note, deltas, details, measure)


def _m(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def tightest(placement: Placement) -> tuple[float, str] | None:
    """Относительный запас до самой тесной нормы и её описание."""
    best: tuple[float, str] | None = None
    for check in placement.checks:
        if check.measured_m is None or not check.threshold_m or check.threshold_m <= 0:
            continue
        # Мягкая норма «на согласование» тоже в счёт: запас по ней отрицательный, балл ноль.
        if check.outcome is CheckOutcome.NO_DATA:
            continue
        margin = (check.measured_m - check.threshold_m) / check.threshold_m
        if best is None or margin < best[0]:
            text = f"{_m(check.measured_m)} м при норме {_m(check.threshold_m)} м ({check.rule_id})"
            best = (margin, text)
    return best


def margin(layout: Layout, params: PlanParams) -> TermResult:
    """Средний запас до ближайшей нормы: полный балл с запасом margin_target и больше."""
    target = params.margin_target
    found = [tightest(p) for p in layout.placements]
    values: list[float | None] = [
        None if item is None else min(1.0, max(0.0, item[0] / target)) for item in found
    ]
    score, deltas, note, measure = _mean_term(
        values, lambda s: f"средний запас до ближайшей нормы - {s:.0%} от цели {target:.0%}", "mean"
    )
    if score is None:
        return layout.empty("измеренных отступов нет")
    details = [
        "" if item is None else f"запас до ближайшей нормы {item[0]:.0%}: {item[1]}"
        for item in found
    ]
    return TermResult(score, note, deltas, details, measure)


# --- Тень и пылезащита --------------------------------------------------------------------


def canopy(
    layout: Layout, site: Site, params: PlanParams, zone_m2: float | None = None
) -> TermResult:
    """Площадь взрослых крон в долях от зоны, где посадка допустима; полный балл при цели.

    Делить на весь участок бессмысленно: проезжая часть, здания и полосы сетей, где сажать
    нельзя, занимают больше 90% границы работ, и доля крон выходит нулём на любом плане.
    Зона допустимости - то место, которое план вообще мог затенить посадками.
    """
    if site.boundary is None or site.area_m2 <= 0:
        return layout.empty("нет границы работ: не от чего считать долю крон")
    boundary = site.boundary
    area = zone_m2 if zone_m2 and zone_m2 > 0 else site.area_m2
    base = "зоны, где посадка допустима," if zone_m2 and zone_m2 > 0 else "участка"
    trees = np.flatnonzero(layout.is_tree)
    target = params.canopy_target
    deltas = np.zeros(layout.size)
    details = [""] * layout.size
    if not len(trees):
        return TermResult(0.0, "деревьев нет", deltas, details, {"share": 0.0})
    circles = shapely.buffer(
        shapely.points(layout.xy[trees]), layout.radius[trees], quad_segs=_CIRCLE_SEGMENTS
    )
    shapely.prepare(boundary)
    covered = float(shapely.intersection(shapely.union_all(circles), boundary).area)
    share = covered / area
    score = min(1.0, share / target)
    index = shapely.STRtree(circles)
    for k, i in enumerate(trees.tolist()):
        own = circles[k]
        near = [j for j in index.query(own, predicate="intersects").tolist() if j != k]
        if near:
            own = shapely.difference(own, shapely.union_all(circles[near]))
        unique = (
            float(own.area)
            if shapely.contains(boundary, own)
            else float(shapely.intersection(own, boundary).area)
        )
        deltas[i] = score - min(1.0, (covered - unique) / area / target)
        if unique >= _MIN_UNIQUE_M2:
            details[i] = (
                f"взрослая крона даёт {unique:.0f} м² тени, которых не даёт больше ни одно дерево"
            )
    note = (
        f"взрослые кроны закрывают {covered:.0f} м², это {share:.0%} площади {base} "
        f"{area:.0f} м², при цели {target:.0%}; от всей границы работ - "
        f"{covered / site.area_m2:.1%}"
    )
    measure = {
        "share": round(share, 4),
        "m2": round(covered),
        "base_m2": round(area),
        "boundary_share": round(covered / site.area_m2, 5),
    }
    return TermResult(score, note, deltas, details, measure)


def dust(layout: Layout, site: Site, params: PlanParams) -> TermResult:
    """Доля бортов под кронами, взвешенная газоустойчивостью вида (0-2 -> 0-1)."""
    if not len(site.curb_segments):
        return layout.empty("бортов в границе работ нет: пылезащиту мерить не по чему")
    target = params.dust_target
    weight = np.array([p.species.gas_tolerance / 2 for p in layout.placements], dtype=np.float64)
    coverage = measure_crowns(site.curb_segments, layout.xy, layout.radius, weight)
    total, count = coverage.weighted_m, coverage.length_m
    share = total / count
    score = min(1.0, share / target)
    deltas = score - np.minimum(1.0, (total - coverage.loss_m) / count / target)
    covered = coverage.covered_m
    details = [
        f"крона прикрывает {coverage.reach_m[i]:.1f} м борта, "
        f"газоустойчивость {p.species.gas_tolerance} из 2"
        if coverage.reach_m[i]
        else ""
        for i, p in enumerate(layout.placements)
    ]
    note = (
        f"под кронами {covered:.1f} м бортов из {count:.1f} ({covered / count:.0%}), "
        f"с поправкой на газоустойчивость {share:.0%} при цели {target:.0%}"
    )
    measure = {"curb_m": count, "covered_m": covered, "share": round(share, 4)}
    return TermResult(score, note, deltas, details, measure)


# --- Сезонность ---------------------------------------------------------------------------


def season(layout: Layout) -> TermResult:
    """Сколько месяцев из 12 есть декоративные посадки и насколько ровно они распределены."""
    months = [sorted(p.species.decor_months) for p in layout.placements]
    base = np.zeros(12)
    for owned in months:
        for month in owned:
            base[month - 1] += 1

    def score_of(tally: NDArray[np.float64]) -> float:
        total = float(tally.sum())
        coverage = float((tally > 0).sum()) / 12
        if total <= 0:
            return 0.0
        shares = tally[tally > 0] / total
        evenness = float(-(shares * np.log(shares)).sum() / math.log(12))
        return 0.5 * coverage + 0.5 * evenness

    if not base.sum():
        return layout.empty("у посадок плана нет месяцев декоративности")
    score = score_of(base)
    cache: dict[tuple[int, ...], float] = {}
    deltas = np.zeros(layout.size)
    details = [""] * layout.size
    for i, owned in enumerate(months):
        key = tuple(owned)
        if key not in cache:
            tally = base.copy()
            for month in owned:
                tally[month - 1] -= 1
            cache[key] = score - score_of(tally)
        deltas[i] = cache[key]
        alone = [_MONTHS_IN[m - 1] for m in owned if base[m - 1] == 1]
        if alone:
            details[i] = f"единственная декоративная посадка в {', '.join(alone)}"
    active = int((base > 0).sum())
    note = f"декоративные посадки есть в {active} месяцах из 12"
    return TermResult(score, note, deltas, details, {"months": active})


# --- Штрафы -------------------------------------------------------------------------------


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
