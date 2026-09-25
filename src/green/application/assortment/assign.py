"""Назначение видов: одна задача оптимизации вместо обхода посадок по очереди.

Жадный обход обделяет тех, кто идёт последним: первые ряды забирают лучшие виды, а квоты
разнообразия («не больше 10% одного вида») при таком обходе ломаются на хвосте. Поэтому
виды назначаются сразу всем, целочисленной задачей.

Квоты 10-20-30 (вид, род, семейство) и верхняя граница доли хвойных - жёсткие ограничения:
план, который их нарушает, сервис не выдаёт. Доля считается от числа реально занятых мест,
а это число - переменная той же задачи: «посадок вида не больше 10% от всех занятых» -
линейное ограничение c_s <= 0,1 * T. На участке, где доля меньше одного растения (для
вида - меньше десяти мест), один экземпляр квоту не нарушает, иначе такой участок нельзя
было бы засадить вовсе; это допущение задано двоичной переменной «ключ взят один раз».

Каждая доля проверяется и в популяции улицы вместе с существующими деревьями:
c_s + E_s <= 0,1 * (T + E). Если вида на улице уже больше доли, новых посадок этого вида
нет вовсе.

Проход в два шага. Сначала структура (ряд, участок группы) получает один вид целиком - так
аллея однородна. Места, которые целиком одним видом в квоты не влезли, вторым шагом
получают виды поодиночке, в тех же квотах с учётом уже занятого. Место, под которое ни один
допустимый вид в квоты не укладывается, остаётся пустым, и это видно в плане.

Нижняя граница доли хвойных мягкая: хвойных мест на участке может не быть, и жёсткий
минимум оставил бы пустым весь план. Недобор записывается в заметки.

Режим заданного ассортимента («25 лип и 15 елей») квоты не применяет: количества задал
человек. Там участок можно занять не целиком (переменная n), иначе счётчики не сходятся.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from green.application.assortment.structures import Structure
    from green.application.params import PlanParams
    from green.domain.planting import Species

MILP = "milp"
GREEDY = "greedy"
GIVEN_MODE = "given"
SPECIES_LEVEL = "вид"
GENUS_LEVEL = "род"
FAMILY_LEVEL = "семейство"
CONIFER_KEY = ("хвойные", "")
_TIME_LIMIT_S = 60.0
# Допустимый зазор до оптимума: цель - премия 10 за каждое занятое место плюс оценка вида,
# 0,5% от неё на плане из трёхсот мест - около полутора мест. Без зазора HiGHS доказывал
# оптимум дольше минуты (Берзарина, 16.09.2026), с зазором - 12 секунд.
_MIP_GAP = 0.005
# Заполнить место важнее, чем выбрать вид с оценкой чуть выше (оценка не больше 1), и
# важнее, чем добрать хвойных до нижней границы коридора.
_FILL_BONUS = 10.0
_CONIFER_PENALTY = 3.0
ROW_KIND = "row"  # структура-ряд (assortment.structures.ROW), без импорта по кругу
_HALF = 0.5  # порог округления двоичной переменной
_EPS = 1e-9

type Key = tuple[str, str]


@dataclass(frozen=True, slots=True)
class Candidate:
    placement_id: str
    structure_id: str
    structure_kind: str
    species: Species
    score: float


@dataclass(frozen=True, slots=True)
class Assignment:
    species_by_placement: Mapping[str, str]
    solver: str
    quota_violations: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())
    # Посадки, получившие вид вторым шагом: их структура одним видом в квоты не влезла.
    split_placements: frozenset[str] = frozenset()
    # Вид -> какая квота выбрана до конца (Quotas.used_up): почему не он у альтернатив.
    used_up: Mapping[str, str] = field(default_factory=dict)


def assign(
    candidates: Sequence[Candidate],
    structures: Sequence[Structure],  # noqa: ARG001 - структура уже записана в Candidate
    catalog: Mapping[str, Species],
    existing: Mapping[str, int],
    params: PlanParams,
) -> Assignment:
    if not candidates:
        return Assignment(species_by_placement={}, solver=MILP)
    if params.assortment_mode == GIVEN_MODE:
        problem = _GivenProblem(candidates, params)
        if params.assortment_solver == GREEDY:
            return problem.solve_greedy()
        return problem.solve_milp() or problem.solve_greedy()
    return _QuotaAssignment(candidates, catalog, existing, params).run()


# --- квоты ---


def _quota_label(key: Key, share: float) -> str:
    level, name = key
    if key == CONIFER_KEY:
        return f"доля хвойных {share:.0%}"
    if level == SPECIES_LEVEL:
        return f"квота вида {share:.0%}"
    if level == GENUS_LEVEL:
        return f"квота рода {name.capitalize()} {share:.0%}"
    return f"квота семейства {name} {share:.0%}"


def allowance(share: float, planned: int) -> int:
    """Сколько растений ключа допускает доля: вниз до целого; один, если доля меньше одного."""
    if share * planned < 1:
        return 1
    return math.floor(share * planned + _EPS)


class Quotas:
    """Квоты 10-20-30 и верхняя граница хвойных: какие ключи у вида и выдержан ли план."""

    def __init__(
        self, catalog: Mapping[str, Species], existing: Mapping[str, int], params: PlanParams
    ) -> None:
        self.catalog = catalog
        self.params = params
        self.shares = {
            SPECIES_LEVEL: params.quota_species,
            GENUS_LEVEL: params.quota_genus,
            FAMILY_LEVEL: params.quota_family,
            CONIFER_KEY[0]: params.conifer_share[1],
        }
        self.existing_total = sum(existing.values())
        self.existing: Counter[Key] = Counter()
        for code, count in existing.items():
            species = catalog.get(code)
            keys = self.keys(species) if species else ((SPECIES_LEVEL, code),)
            for key in keys:
                if key != CONIFER_KEY:  # коридор хвойных задан для плана, не для популяции
                    self.existing[key] += count

    def adapt(self, candidates: Sequence[Candidate]) -> None:
        """Квота уровня не строже, чем позволяет выбор на месте: 1 / (медиана вариантов).

        Если на типичном месте нормы оставляют четыре вида из двух семейств, квоты 10% и 30%
        невыполнимы при любом числе посадок: сумма долей меньше единицы, и задача оставляет
        участок вовсе без деревьев (Измайловская площадь: 0 из 38 мест). Тот же принцип, что у
        цели разнообразия в индексе: не требовать больше видов, чем допускают нормы.
        """
        by_place: defaultdict[str, list[Species]] = defaultdict(list)
        for candidate in candidates:
            by_place[candidate.placement_id].append(candidate.species)
        if not by_place:
            return
        for level, index in ((SPECIES_LEVEL, 0), (GENUS_LEVEL, 1), (FAMILY_LEVEL, 2)):
            options = sorted(
                len({self.keys(s)[index] for s in species}) for species in by_place.values()
            )
            median = options[len(options) // 2]
            if median > 0:
                self.shares[level] = max(self.shares[level], 1.0 / median)

    def keys(self, species: Species) -> tuple[Key, ...]:
        keys: tuple[Key, ...] = (
            (SPECIES_LEVEL, species.code),
            (GENUS_LEVEL, species.genus),
            (FAMILY_LEVEL, species.family),
        )
        return (*keys, CONIFER_KEY) if species.is_conifer else keys

    def share(self, key: Key) -> float:
        return self.shares[key[0]]

    def exhausted(self, key: Key) -> bool:
        """На улице уже больше доли: новых посадок с этим ключом не будет."""
        grown = self.existing[key]
        return grown > 0 and grown > self.share(key) * self.existing_total + _EPS

    def counts(self, chosen: Mapping[str, str]) -> Counter[Key]:
        used: Counter[Key] = Counter()
        for code in chosen.values():
            for key in self.keys(self.catalog[code]):
                used[key] += 1
        return used

    def violations(self, chosen: Mapping[str, str]) -> tuple[str, ...]:
        """Проверка итогового плана той же арифметикой, что в задаче."""
        planned = len(chosen)
        found = []
        for key, count in sorted(self.counts(chosen).items()):
            share = self.share(key)
            label = f"{key[0]} {key[1]}".strip()
            if count > allowance(share, planned):
                found.append(f"{label}: {count} из {planned} в плане, доля {share:.0%}")
            if key == CONIFER_KEY or not self.existing_total:
                continue
            if self.exhausted(key):
                found.append(f"{label}: доля на улице уже выбрана, в плане {count}")
                continue
            population = planned + self.existing_total
            if count + self.existing[key] > math.floor(share * population + _EPS):
                found.append(f"{label}: {count + self.existing[key]} из {population} на улице")
        return tuple(found)

    def used_up(self, chosen: Mapping[str, str]) -> dict[str, str]:
        """Какая квота не пускает в план ещё одно растение вида: причина для альтернатив.

        Вид с оценкой выше выбранного уступил либо квоте, либо однородности структуры;
        эксперту нужна одна из двух причин, а не обе через «или».
        """
        planned = len(chosen)
        counts = self.counts(chosen)
        found: dict[str, str] = {}
        for code, species in self.catalog.items():
            for key in self.keys(species):
                reason = self._used_up(key, counts[key], planned)
                if reason:
                    found[code] = reason
                    break
        return found

    def _used_up(self, key: Key, count: int, planned: int) -> str:
        share = self.share(key)
        label = _quota_label(key, share)
        if count >= allowance(share, planned):
            return f"{label} выбрана"
        if key == CONIFER_KEY or not self.existing_total:
            return ""
        population = planned + self.existing_total
        if self.exhausted(key) or count + self.existing[key] >= math.floor(
            share * population + _EPS
        ):
            return f"{label} выбрана с существующими деревьями"
        return ""

    def exhausted_notes(self, codes: Sequence[str]) -> list[str]:
        keys = sorted({k for code in codes for k in self.keys(self.catalog[code])})
        return [
            f"{key[0]} {key[1]}: на улице уже {self.existing[key]} из {self.existing_total} "
            "растений, доля выбрана, новых посадок нет"
            for key in keys
            if key != CONIFER_KEY and self.exhausted(key)
        ]


# --- назначение с квотами ---


class _QuotaAssignment:
    def __init__(
        self,
        candidates: Sequence[Candidate],
        catalog: Mapping[str, Species],
        existing: Mapping[str, int],
        params: PlanParams,
    ) -> None:
        self.catalog = catalog
        self.params = params
        self.quotas = Quotas(catalog, existing, params)
        usable = [c for c in candidates if c.species.code in catalog]
        self.candidates = sorted(usable, key=lambda c: (c.placement_id, c.species.code))
        self.codes = sorted({c.species.code for c in self.candidates})
        if params.quota_adaptive:
            self.quotas.adapt(self.candidates)

    def run(self) -> Assignment:
        notes: list[str] = []
        if self.params.assortment_solver == GREEDY:
            notes.append("виды назначены жадным обходом структур по настройке профиля")
            chosen, split = _greedy_plan(self.candidates, self.quotas)
            return self._assignment(chosen, split, GREEDY, notes)
        by_structure: defaultdict[str, list[Candidate]] = defaultdict(list)
        for candidate in self.candidates:
            by_structure[candidate.structure_id].append(candidate)
        whole = _milp(by_structure, {}, self.quotas)
        singles: defaultdict[str, list[Candidate]] = defaultdict(list)
        if whole is not None:
            for candidate in self.candidates:
                if candidate.placement_id not in whole:
                    singles[candidate.placement_id].append(candidate)
        rest = _milp(singles, whole, self.quotas) if whole is not None and singles else {}
        if whole is None or rest is None:
            notes.append("решатель не справился, виды назначены жадным обходом структур")
            chosen, split = _greedy_plan(self.candidates, self.quotas)
            return self._assignment(chosen, split, GREEDY, notes)
        return self._assignment({**whole, **rest}, set(rest), MILP, notes)

    def _assignment(
        self, chosen: Mapping[str, str], split: set[str], solver: str, notes: list[str]
    ) -> Assignment:
        notes = [*notes, *self.quotas.exhausted_notes(self.codes), *self._conifer_notes(chosen)]
        if split:
            split_note = (
                f"{len(split)} посадок получили вид вне своей структуры: одним видом структура "
                "в квоты разнообразия не влезла"
            )
            notes.append(split_note)
        return Assignment(
            species_by_placement=dict(sorted(chosen.items())),
            solver=solver,
            quota_violations=self.quotas.violations(chosen),
            notes=tuple(notes),
            split_placements=frozenset(split),
            used_up=self.quotas.used_up(chosen),
        )

    def _conifer_notes(self, chosen: Mapping[str, str]) -> list[str]:
        low = self.params.conifer_share[0]
        minimum = math.ceil(low * len(chosen) - _EPS)
        if minimum <= 0:
            return []
        if not any(self.catalog[c].is_conifer for c in self.codes):
            return ["доля хвойных не выдержана снизу: допустимых хвойных на участке нет"]
        conifers = sum(1 for code in chosen.values() if self.catalog[code].is_conifer)
        if conifers >= minimum:
            return []
        short_note = (
            f"доля хвойных ниже коридора: {conifers} из {len(chosen)} при минимуме {minimum} "
            "(нижняя граница мягкая)"
        )
        return [short_note]


def _milp(
    groups: Mapping[str, list[Candidate]], fixed: Mapping[str, str], quotas: Quotas
) -> dict[str, str] | None:
    """y - группа занята видом целиком (двоичная), b - ключ взят в одном экземпляре."""
    members: defaultdict[tuple[str, str], list[Candidate]] = defaultdict(list)
    for group_id, candidates in groups.items():
        for candidate in candidates:
            members[(group_id, candidate.species.code)].append(candidate)
    pairs = sorted(members)
    if not pairs:
        return {}
    weights = np.array([float(len(members[pair])) for pair in pairs])
    in_key: defaultdict[Key, list[int]] = defaultdict(list)
    for position, (_, code) in enumerate(pairs):
        for key in quotas.keys(quotas.catalog[code]):
            in_key[key].append(position)
    keys = sorted(in_key)
    count = len(pairs)
    # Исключение «один экземпляр» нужно, пока доля меньше одного растения от числа ЗАНЯТЫХ
    # мест, а не от числа мест вообще: при 19 местах, из которых квоты дают занять меньше
    # десяти, доля вида 10% - это меньше одного растения, и без исключения задача находила
    # единственное решение - ноль посадок (Багрицкого, Измайловская площадь, 23.09.2026).
    # Поэтому двоичные переменные заводятся, пока мест меньше quota_single_places долей; на
    # большом плане занято всегда больше десятка, а двоичные переменные с большой константой
    # делают задачу в десятки раз тяжелее.
    places = len(fixed) + len({c.placement_id for g in groups.values() for c in g})
    limit = quotas.params.quota_single_places
    small = [key for key in keys if places * quotas.share(key) < limit]
    single = {key: count + i for i, key in enumerate(small)}  # столбцы b
    slack = count + len(small)  # недобор хвойных до нижней границы
    # Мягкие квоты: перебор доли ключа - непрерывная переменная со штрафом в цели. Штраф меньше
    # премии за занятое место, поэтому место не пустеет, но из видов берётся тот, что квоту
    # держит, пока такой есть.
    over = _soft_columns(keys, slack + 1, quotas.params.quota_penalty)
    size = slack + 1 + len(over)
    rows = _one_species_per_group(pairs, size)
    big = float(len(fixed) + weights.sum())
    ctx = _Context(weights, quotas, quotas.counts(fixed), float(len(fixed)), single, big, over)
    for key in keys:
        _share_rows(rows, key, in_key[key], ctx)
    _conifer_floor(rows, in_key.get(CONIFER_KEY, []), ctx, slack)
    cost, upper, integrality = _objective(pairs, members, size, quotas.params)
    cost[slack] = _CONIFER_PENALTY
    upper[slack] = big
    integrality[slack] = 0
    for column in over.values():
        cost[column] = quotas.params.quota_penalty
        upper[column] = big
        integrality[column] = 0
    result = milp(
        c=cost,
        constraints=rows.constraint(),
        integrality=integrality,
        bounds=Bounds(np.zeros(size), upper),
        options={"time_limit": _TIME_LIMIT_S, "mip_rel_gap": _MIP_GAP},
    )
    if result.x is None:
        return None
    chosen = {
        candidate.placement_id: pair[1]
        for position, pair in enumerate(pairs)
        if result.x[position] > _HALF
        for candidate in members[pair]
    }
    # Кончилось время, но допустимое решение найдено: берём его, если квоты целы (при мягких
    # квотах перебор доли допустим по постановке).
    if not result.success and not over and quotas.violations({**fixed, **chosen}):
        return None
    return chosen


def _soft_columns(keys: Sequence[Key], first: int, penalty: float) -> dict[Key, int]:
    """Столбцы перебора мягких квот: по одному на ключ, кроме хвойных (у них свой коридор)."""
    if penalty <= 0:
        return {}
    soft = [key for key in keys if key != CONIFER_KEY]
    return {key: first + i for i, key in enumerate(soft)}


def _objective(
    pairs: Sequence[tuple[str, str]],
    members: Mapping[tuple[str, str], list[Candidate]],
    size: int,
    params: PlanParams,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Цель: премия за занятое место (у мест ряда - с надбавкой) плюс оценка вида."""
    cost = np.zeros(size)
    for position, pair in enumerate(pairs):
        cost[position] = -sum(
            c.score + _FILL_BONUS + (params.alley_priority if c.structure_kind == ROW_KIND else 0.0)
            for c in members[pair]
        )
    return cost, np.ones(size), np.ones(size)


def _one_species_per_group(pairs: Sequence[tuple[str, str]], size: int) -> _Rows:
    rows = _Rows(size)
    by_group: defaultdict[str, dict[int, float]] = defaultdict(dict)
    for position, (group_id, _) in enumerate(pairs):
        by_group[group_id][position] = 1.0
    for entries in by_group.values():
        rows.add(entries, 0.0, 1.0)
    return rows


@dataclass(frozen=True, slots=True)
class _Context:
    """Общие части строк задачи: веса пар, квоты, уже занятое первым шагом."""

    weights: np.ndarray
    quotas: Quotas
    used: Counter[Key]
    fixed_total: float
    single: Mapping[Key, int]
    big: float
    over: Mapping[Key, int] = field(default_factory=dict)  # столбцы перебора мягкой квоты


def _share_rows(rows: _Rows, key: Key, positions: Sequence[int], ctx: _Context) -> None:
    """Доля ключа в плане (с исключением «один экземпляр») и в популяции улицы."""
    weights, quotas, single, big = ctx.weights, ctx.quotas, ctx.single, ctx.big
    used, fixed_total = ctx.used[key], ctx.fixed_total
    share = quotas.share(key)
    inside = set(positions)
    if key != CONIFER_KEY and quotas.existing_total and quotas.exhausted(key):
        rows.add({p: weights[p] for p in positions}, -np.inf, float(-used))
        return
    # c + F - share * (F_T + T) - b <= 0: доля в плане, b разрешает один экземпляр.
    plan = {p: weights[p] * ((1.0 if p in inside else 0.0) - share) for p in range(len(weights))}
    if key in ctx.over:
        plan[ctx.over[key]] = -1.0
    if key in single:
        plan[single[key]] = -1.0
        # b = 1 только если ключ взят не больше одного раза: c + F + big * b <= 1 + big.
        once = {p: weights[p] for p in positions}
        once[single[key]] = big
        rows.add(once, -np.inf, 1.0 + big - used)
    rows.add(_nonzero(plan), -np.inf, share * fixed_total - used)
    if key == CONIFER_KEY or not quotas.existing_total:
        return
    grown = float(quotas.existing[key])
    population = {
        p: weights[p] * ((1.0 if p in inside else 0.0) - share) for p in range(len(weights))
    }
    rows.add(
        _nonzero(population),
        -np.inf,
        share * (fixed_total + quotas.existing_total) - grown - used,
    )


def _conifer_floor(rows: _Rows, positions: Sequence[int], ctx: _Context, slack: int) -> None:
    """Мягкая нижняя граница хвойных: c + F - low * (F_T + T) + s >= 0."""
    weights, used, fixed_total = ctx.weights, ctx.used, ctx.fixed_total
    low = ctx.quotas.params.conifer_share[0]
    if low <= 0 or not positions:
        return
    inside = set(positions)
    entries = {p: weights[p] * ((1.0 if p in inside else 0.0) - low) for p in range(len(weights))}
    entries[slack] = 1.0
    rows.add(_nonzero(entries), low * fixed_total - used[CONIFER_KEY], np.inf)


def _nonzero(entries: Mapping[int, float]) -> dict[int, float]:
    return {k: v for k, v in entries.items() if abs(v) > _EPS}


def _greedy_plan(
    candidates: Sequence[Candidate], quotas: Quotas
) -> tuple[dict[str, str], set[str]]:
    """Запасной путь без решателя: наибольшее число мест T, которое жадный обход занимает
    целиком при допусках, посчитанных от того же T.

    Заполнено ровно T мест при допусках от T - значит, квоты на итоговом плане выдержаны по
    построению, подрезать ничего не нужно. Прежний вариант брал допуски от всех мест и
    срезал превышение по одной посадке: каждое срезание уменьшало план и допуски остальных,
    и на Берзарина оставалось 110 мест из 301 при 280 у решателя. T ищется двоичным поиском.
    """
    places = len({c.placement_id for c in candidates})
    full = _greedy_fill(candidates, quotas, places)
    if len(full[0]) == places:  # все места заняты - искать меньшее T незачем
        return full
    best: tuple[dict[str, str], set[str]] = ({}, set())
    low, high = 1, places - 1
    while low <= high:
        target = (low + high) // 2
        chosen, split = _greedy_fill(candidates, quotas, target)
        if len(chosen) == target:
            best = (chosen, split)
            low = target + 1
        else:
            high = target - 1
    return best


def _greedy_fill(
    candidates: Sequence[Candidate], quotas: Quotas, target: int
) -> tuple[dict[str, str], set[str]]:
    """Не больше target мест: структуры целиком, затем оставшиеся места поодиночке.

    Порядок - сначала самые стеснённые (меньше всего допустимых видов), вид - с наибольшим
    остатком допуска: иначе крупные массивы газона забирают долю видов, которые одни проходят
    у борта, и аллея остаётся пустой.
    """
    fill = _Fill(quotas, target)
    by_structure: defaultdict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        by_structure[candidate.structure_id].append(candidate)
    for members in sorted(by_structure.values(), key=_tightness):
        fill.whole(members)
    rest: defaultdict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.placement_id not in fill.chosen:
            rest[candidate.placement_id].append(candidate)
    for options in sorted(rest.values(), key=_tightness):
        fill.single(options)
    return fill.chosen, fill.split


def _tightness(members: Sequence[Candidate]) -> tuple[int, int, str]:
    codes = {c.species.code for c in members}
    places = {c.placement_id for c in members}
    return (len(codes), -len(places), min(c.placement_id for c in members))


class _Fill:
    """Состояние жадного заполнения: занятое по ключам и выбранные виды."""

    def __init__(self, quotas: Quotas, target: int) -> None:
        self.quotas = quotas
        self.target = target
        self.used: Counter[Key] = Counter()
        self.chosen: dict[str, str] = {}
        self.split: set[str] = set()

    def room(self, code: str) -> int:
        """Сколько ещё посадок вида допускают все его ключи при target местах."""
        return min(
            _limit(self.quotas, key, self.target) - self.used[key]
            for key in self.quotas.keys(self.quotas.catalog[code])
        )

    def take(self, code: str, members: Sequence[Candidate]) -> None:
        for candidate in members:
            self.chosen[candidate.placement_id] = code
        for key in self.quotas.keys(self.quotas.catalog[code]):
            self.used[key] += len(members)

    def whole(self, members: Sequence[Candidate]) -> None:
        places = {c.placement_id for c in members}
        if len(self.chosen) + len(places) > self.target:
            return
        options: defaultdict[str, list[Candidate]] = defaultdict(list)
        for candidate in members:
            options[candidate.species.code].append(candidate)
        fitting = [
            (self.room(code), sum(c.score for c in group), code, group)
            for code, group in options.items()
            if len(group) == len(places)
        ]
        fitting = [item for item in fitting if item[0] >= len(places)]
        if fitting:
            _, _, code, group = max(fitting, key=lambda item: (item[0], item[1], item[2]))
            self.take(code, group)

    def single(self, options: Sequence[Candidate]) -> None:
        if len(self.chosen) >= self.target:
            return
        fitting = [(self.room(c.species.code), c.score, c.species.code, c) for c in options]
        fitting = [item for item in fitting if item[0] >= 1]
        if fitting:
            candidate = max(fitting, key=lambda item: (item[0], item[1], item[2]))[3]
            self.take(candidate.species.code, (candidate,))
            self.split.add(candidate.placement_id)


def _limit(quotas: Quotas, key: Key, planned: int) -> int:
    """Наибольшее число посадок ключа при planned местах (та же арифметика, что в _fits)."""
    share = quotas.share(key)
    limit = allowance(share, planned)
    if key == CONIFER_KEY or not quotas.existing_total:
        return limit
    if quotas.exhausted(key):
        return 0
    population = math.floor(share * (planned + quotas.existing_total) + _EPS)
    return min(limit, population - quotas.existing[key])


# --- заданный ассортимент ---


class _Rows:
    """Разреженная матрица ограничений, собираемая строка за строкой."""

    def __init__(self, columns: int) -> None:
        self.columns = columns
        self._rows: list[int] = []
        self._cols: list[int] = []
        self._values: list[float] = []
        self.lower: list[float] = []
        self.upper: list[float] = []

    def add(self, entries: Mapping[int, float], low: float, high: float) -> None:
        if not entries:
            return
        index = len(self.lower)
        self._rows += [index] * len(entries)
        self._cols += list(entries)
        self._values += list(entries.values())
        self.lower.append(low)
        self.upper.append(high)

    def constraint(self) -> LinearConstraint:
        matrix = coo_matrix(
            (self._values, (self._rows, self._cols)), shape=(len(self.lower), self.columns)
        ).tocsr()
        return LinearConstraint(matrix, np.array(self.lower), np.array(self.upper))


class _GivenProblem:
    """Режим «вот 25 лип и 15 елей»: количества - верхняя граница, квоты не применяются."""

    def __init__(self, candidates: Sequence[Candidate], params: PlanParams) -> None:
        self.params = params
        self.candidates = sorted(candidates, key=lambda c: (c.placement_id, c.species.code))
        self.by_structure: defaultdict[str, list[Candidate]] = defaultdict(list)
        for candidate in self.candidates:
            self.by_structure[candidate.structure_id].append(candidate)
        self.members: defaultdict[tuple[str, str], list[Candidate]] = defaultdict(list)
        for candidate in self.candidates:
            self.members[(candidate.structure_id, candidate.species.code)].append(candidate)
        self.pairs = sorted(self.members)
        self.index = {pair: position for position, pair in enumerate(self.pairs)}

    def solve_milp(self) -> Assignment | None:
        pairs = len(self.pairs)
        size = 2 * pairs  # y - участок занят видом, n - сколько его посадок занято
        rows = _Rows(size)
        for structure_id in sorted(self.by_structure):
            codes = sorted({c.species.code for c in self.by_structure[structure_id]})
            rows.add({self.index[(structure_id, code)]: 1.0 for code in codes}, 0.0, 1.0)
        for pair, position in self.index.items():
            rows.add(
                {position + pairs: 1.0, position: -float(len(self.members[pair]))}, -np.inf, 0.0
            )
        for code, count in sorted(self.params.given_assortment.items()):
            entries = {
                position + pairs: 1.0 for pair, position in self.index.items() if pair[1] == code
            }
            rows.add(entries, 0.0, float(count))
        cost = np.zeros(size)
        for pair, position in self.index.items():
            members = self.members[pair]
            cost[position + pairs] = -(sum(c.score for c in members) / len(members) + _FILL_BONUS)
        upper = np.concatenate(
            [np.ones(pairs), [float(len(self.members[pair])) for pair in self.pairs]]
        )
        result = milp(
            c=cost,
            constraints=rows.constraint(),
            integrality=np.ones(size),
            bounds=Bounds(np.zeros(size), upper),
            options={"time_limit": _TIME_LIMIT_S},
        )
        if not result.success or result.x is None:
            return None
        chosen: dict[str, str] = {}
        for pair, position in self.index.items():
            take = round(float(result.x[position + pairs]))
            ranked = sorted(self.members[pair], key=lambda c: (-c.score, c.placement_id))
            for candidate in ranked[:take]:
                chosen[candidate.placement_id] = pair[1]
        notes = ["режим заданного ассортимента: квоты разнообразия не применяются"]
        notes += self._shortfall(chosen)
        return Assignment(
            species_by_placement=dict(sorted(chosen.items())), solver=MILP, notes=tuple(notes)
        )

    def solve_greedy(self) -> Assignment:
        left = dict(self.params.given_assortment)
        chosen: dict[str, str] = {}
        order = sorted(self.by_structure, key=lambda s: (-len(self.by_structure[s]), s))
        for structure_id in order:
            options: defaultdict[str, list[Candidate]] = defaultdict(list)
            for candidate in self.by_structure[structure_id]:
                options[candidate.species.code].append(candidate)
            ranked = sorted(
                options.items(),
                key=lambda item: (-len(item[1]), -sum(c.score for c in item[1]), item[0]),
            )
            for code, candidates in ranked:
                take = min(len(candidates), left.get(code, 0))
                if take <= 0:
                    continue
                best = sorted(candidates, key=lambda c: (-c.score, c.placement_id))[:take]
                for candidate in best:
                    chosen[candidate.placement_id] = code
                left[code] -= take
                break
        notes = (
            "режим заданного ассортимента: квоты разнообразия не применяются",
            "виды назначены жадным обходом структур",
            *self._shortfall(chosen),
        )
        return Assignment(
            species_by_placement=dict(sorted(chosen.items())), solver=GREEDY, notes=notes
        )

    def _shortfall(self, chosen: Mapping[str, str]) -> list[str]:
        """Заданное количество - верхняя граница: остаток между участками не делится."""
        placed = Counter(chosen.values())
        short = {
            code: count - placed.get(code, 0)
            for code, count in sorted(self.params.given_assortment.items())
            if count - placed.get(code, 0) > 0
        }
        if not short:
            return []
        listed = ", ".join(f"{code} на {value}" for code, value in short.items())
        return [
            (
                f"заданные количества выдержаны не полностью (не хватило {listed}): "
                "участок занимается одним видом, остаток между участками не делится"
            )
        ]
