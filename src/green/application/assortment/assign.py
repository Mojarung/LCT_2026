"""Назначение видов: одна задача оптимизации вместо обхода посадок по очереди.

Жадный обход обделяет тех, кто идёт последним: первые ряды забирают лучшие виды, а квоты
разнообразия («не больше 10% одного вида») при таком обходе ломаются на хвосте. Поэтому
виды назначаются сразу всем, целочисленной задачей.

Квоты 10-20-30 (вид, род, семейство) и верхняя граница доли хвойных - жёсткие ограничения:
план, который их нарушает, сервис не выдаёт. Доля считается от числа реально занятых мест,
а это число - переменная той же задачи: «посадок вида не больше 10% от всех занятых» -
линейное ограничение c_s <= 0,1 * T. На участке, где доля меньше одного растения (для
вида - меньше десяти мест), один экземпляр квоту не нарушает, иначе такой участок нельзя
было бы засадить вовсе; это допущение задано двоичной переменной для каждой доли,
которая действует только пока фактически занятых мест меньше порога этой доли.

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
    """Keep the small MILP's incumbent; retry exact one-specimen quotas only if useful."""
    original = _solve_milp(groups, fixed, quotas, exceptions_enabled=False)
    shares = {share for share in quotas.shares.values() if 0 < share < 1}
    if not shares:
        return original
    largest_small_total = max(math.ceil(1 / share - _EPS) - 1 for share in shares)
    available = {candidate.placement_id for members in groups.values() for candidate in members}
    small_new = min(len(available), max(0, largest_small_total - len(fixed)))
    max_score = max(
        (candidate.score for members in groups.values() for candidate in members), default=0
    )
    upper_bound = small_new * max(0.0, _FILL_BONUS + max_score)
    if original is not None and _assignment_value(original, groups, fixed, quotas) >= upper_bound:
        return original
    corrected = _solve_milp(groups, fixed, quotas, exceptions_enabled=True)
    if corrected is None:
        return original
    if (
        original is None
        or _assignment_value(corrected, groups, fixed, quotas)
        > _assignment_value(original, groups, fixed, quotas) + _EPS
    ):
        return corrected
    return original


def _assignment_value(
    chosen: Mapping[str, str],
    groups: Mapping[str, list[Candidate]],
    fixed: Mapping[str, str],
    quotas: Quotas,
) -> float:
    scores = {
        (candidate.placement_id, candidate.species.code): candidate.score
        for members in groups.values()
        for candidate in members
    }
    gain = sum(_FILL_BONUS + scores[(placement_id, code)] for placement_id, code in chosen.items())
    total = len(fixed) + len(chosen)
    conifers = sum(quotas.catalog[code].is_conifer for code in (*fixed.values(), *chosen.values()))
    conifer_available = any(
        candidate.species.is_conifer for members in groups.values() for candidate in members
    )
    deficit = (
        max(0.0, quotas.params.conifer_share[0] * total - conifers) if conifer_available else 0.0
    )
    return gain - _CONIFER_PENALTY * deficit


def _solve_milp(  # noqa: C901 - quota rows and bounds share the same indexed variables
    groups: Mapping[str, list[Candidate]],
    fixed: Mapping[str, str],
    quotas: Quotas,
    *,
    exceptions_enabled: bool,
) -> dict[str, str] | None:
    """y selects one species per group; z enables one-specimen small-plan quotas."""
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
    # T is the number actually selected, not the number of available places.
    # One binary per distinct quota share enables a single specimen only while
    # T * share < 1. Sharing the binary across keys avoids one binary per species.
    shares = (
        sorted({quotas.share(key) for key in keys if 0 < quotas.share(key) < 1})
        if exceptions_enabled
        else []
    )
    exceptions = {share: count + i for i, share in enumerate(shares)}
    slack = count + len(shares)  # недобор хвойных до нижней границы
    size = slack + 1
    rows = _one_species_per_group(pairs, size)
    capacity: defaultdict[str, int] = defaultdict(int)
    for pair in pairs:
        capacity[pair[0]] = max(capacity[pair[0]], len(members[pair]))
    maximum_total = float(len(fixed) + sum(capacity.values()))
    _exception_rows(rows, weights, exceptions, float(len(fixed)), maximum_total)
    ctx = _Context(weights, quotas, quotas.counts(fixed), float(len(fixed)), exceptions)
    for key in keys:
        _share_rows(rows, key, in_key[key], ctx)
    _conifer_floor(rows, in_key.get(CONIFER_KEY, []), ctx, slack)
    cost = np.zeros(size)
    for position, pair in enumerate(pairs):
        cost[position] = -sum(c.score + _FILL_BONUS for c in members[pair])
    cost[slack] = _CONIFER_PENALTY
    upper = np.ones(size)
    upper[slack] = maximum_total
    integrality = np.ones(size)
    integrality[slack] = 0
    constraint = rows.constraint()
    result = milp(
        c=cost,
        constraints=constraint,
        integrality=integrality,
        bounds=Bounds(np.zeros(size), upper),
        options={"time_limit": _TIME_LIMIT_S, "mip_rel_gap": _MIP_GAP},
    )
    if result.x is None or not _valid_primal(result.x, constraint, upper, slack):
        return None
    selected = [pair for position, pair in enumerate(pairs) if result.x[position] > _HALF]
    chosen = {candidate.placement_id: pair[1] for pair in selected for candidate in members[pair]}
    if (
        len(chosen) != sum(len(members[pair]) for pair in selected)
        or set(chosen) & fixed.keys()
        or quotas.violations({**fixed, **chosen})
    ):
        return None
    return chosen


def _valid_primal(
    primal: np.ndarray, constraint: LinearConstraint, upper: np.ndarray, binary: int
) -> bool:
    """A timeout's primal must still satisfy every row, bound, and binary variable."""
    values = np.asarray(primal, dtype=float)
    if values.shape != upper.shape or not np.isfinite(values).all():
        return False
    tolerance = 1e-6
    if (
        (values < -tolerance).any()
        or (values > upper + tolerance).any()
        or (np.abs(values[:binary] - np.rint(values[:binary])) > tolerance).any()
    ):
        return False
    measured = constraint.A @ values
    return bool(
        (measured >= constraint.lb - tolerance).all()
        and (measured <= constraint.ub + tolerance).all()
    )


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
    exceptions: Mapping[float, int]


def _exception_rows(
    rows: _Rows,
    weights: np.ndarray,
    exceptions: Mapping[float, int],
    fixed_total: float,
    maximum_total: float,
) -> None:
    """An exception can turn on only below the share's first whole plant."""
    for share, column in exceptions.items():
        largest_exempt_total = math.ceil(1 / share - _EPS) - 1
        excess = maximum_total - largest_exempt_total
        if excess <= 0:
            continue
        entries = dict(enumerate(weights))
        entries[column] = excess
        rows.add(entries, -np.inf, maximum_total - fixed_total)


def _share_rows(rows: _Rows, key: Key, positions: Sequence[int], ctx: _Context) -> None:
    """Доля ключа в плане (с исключением «один экземпляр») и в популяции улицы."""
    weights, quotas = ctx.weights, ctx.quotas
    used, fixed_total = ctx.used[key], ctx.fixed_total
    share = quotas.share(key)
    inside = set(positions)
    if key != CONIFER_KEY and quotas.existing_total and quotas.exhausted(key):
        rows.add({p: weights[p] for p in positions}, -np.inf, float(-used))
        return
    # c + F - share * (F_T + T) - z <= 0; z is shared by keys with this share.
    plan = {p: weights[p] * ((1.0 if p in inside else 0.0) - share) for p in range(len(weights))}
    if share in ctx.exceptions:
        plan[ctx.exceptions[share]] = -1.0
    exception = 1.0 if share == 0 else 0.0
    rows.add(_nonzero(plan), -np.inf, share * fixed_total - used + exception)
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
