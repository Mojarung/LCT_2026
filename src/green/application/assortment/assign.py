"""Назначение видов: одна задача оптимизации вместо обхода посадок по очереди.

Жадный обход обделяет тех, кто идёт последним: первые ряды забирают лучшие виды, а квоты
разнообразия («не больше 10% одного вида») при таком обходе почти всегда ломаются на
хвосте. Поэтому виды назначаются сразу всем, целочисленной задачей.

Переменная одна: y[структура, вид] - «этот участок занят этим видом». Посадка внутри
структуры получает вид структуры, если проходит по ней фильтры, иначе остаётся без вида.
Однородность ряда и участка группы обеспечена самой моделью, а не ограничением, поэтому
задача маленькая: сотни переменных вместо десятков тысяч. На варианте с переменной на
каждую пару «посадка - вид» те же сорок посадок считались три секунды - квоты, натянутые
на тысячи двоичных переменных, дают тяжёлое дерево поиска.

Квоты 10-20-30 по виду, роду и семейству и доля хвойных заданы мягко: у каждой есть
переменная превышения со штрафом. Жёсткая квота противоречит однородности ряда (10% от
тридцати посадок - три дерева, а ряд из десяти требует десяти одного вида) и оставила бы
посадки пустыми; мягкая позволяет превысить долю ровно настолько, насколько иначе места
остались бы без вида, и показывает превышение в сводке.

Если решатель не справился (нет решения или кончилось время), работает жадный запасной
путь, и факт этого попадает и в предупреждения прогона, и в сводку.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from green.application.assortment.structures import SINGLE

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from green.application.assortment.structures import Structure
    from green.application.params import PlanParams
    from green.domain.planting import Species

MILP = "milp"
GREEDY = "greedy"
_TIME_LIMIT_S = 60.0
# Веса в цели упорядочены по важности: заполнить посадку важнее, чем выдержать квоту,
# а выдержать квоту важнее, чем выбрать вид с оценкой чуть выше (оценка не больше 1).
_FILL_BONUS = 10.0
_QUOTA_PENALTY = 3.0
_MIN_STRUCTURE = 2  # у одиночки однородность не ограничивают
_HALF = 0.5  # порог округления двоичной переменной
_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class Candidate:
    placement_id: str
    structure_id: str
    structure_kind: str
    species: Species
    score: float


@dataclass(frozen=True, slots=True)
class _QuotaSpec:
    """Мягкая доля: столбцы задачи, допуск и направление ограничения."""

    label: str
    columns: Mapping[int, float]
    cap: float
    at_least: bool = False


@dataclass(frozen=True, slots=True)
class Assignment:
    species_by_placement: Mapping[str, str]
    solver: str
    quota_violations: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())


def assign(
    candidates: Sequence[Candidate],
    structures: Sequence[Structure],
    catalog: Mapping[str, Species],
    existing: Mapping[str, int],
    params: PlanParams,
) -> Assignment:
    if not candidates:
        return Assignment(species_by_placement={}, solver=MILP)
    problem = _Problem(candidates, structures, catalog, existing, params)
    if params.assortment_solver == GREEDY:
        return problem.solve_greedy()
    return problem.solve_milp() or problem.solve_greedy()


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


class _Problem:
    """Общие индексы для обоих путей решения."""

    def __init__(
        self,
        candidates: Sequence[Candidate],
        structures: Sequence[Structure],
        catalog: Mapping[str, Species],
        existing: Mapping[str, int],
        params: PlanParams,
    ) -> None:
        self.params = params
        self.catalog = catalog
        self.existing = existing
        self.candidates = sorted(candidates, key=lambda c: (c.placement_id, c.species.code))
        self.placements = sorted({c.placement_id for c in self.candidates})
        self.codes = sorted({c.species.code for c in self.candidates})
        self.kinds = {s.structure_id: s.kind for s in structures}
        self.by_structure: defaultdict[str, list[Candidate]] = defaultdict(list)
        for candidate in self.candidates:
            self.by_structure[candidate.structure_id].append(candidate)
        # Что даёт вид структуре: сколько её посадок он займёт и какую сумму оценок принесёт.
        self.members: defaultdict[tuple[str, str], list[Candidate]] = defaultdict(list)
        for candidate in self.candidates:
            self.members[(candidate.structure_id, candidate.species.code)].append(candidate)
        self.pairs = sorted(self.members)
        self.index = {pair: position for position, pair in enumerate(self.pairs)}
        self.structures = sorted(self.by_structure)

    # --- целочисленная задача ---

    def solve_milp(self) -> Assignment | None:
        given = self.params.assortment_mode == "given"
        specs = [] if given else self._quota_specs()
        fixed = len(self.pairs)
        size = fixed + len(specs)
        rows = _Rows(size)
        notes: list[str] = []
        for structure_id in self.structures:
            rows.add(
                {self.index[(structure_id, code)]: 1.0 for code in self._codes_of(structure_id)},
                0.0,
                1.0,
            )
        if given:
            for code, count in sorted(self.params.given_assortment.items()):
                rows.add(self._columns({code}), 0.0, float(count))
            notes.append("режим заданного ассортимента: квоты разнообразия не применяются")
        else:
            notes += self._conifer_note()
        for offset, spec in enumerate(specs):
            slack = fixed + offset
            if spec.at_least:
                rows.add({**spec.columns, slack: 1.0}, spec.cap, np.inf)
            else:
                rows.add({**spec.columns, slack: -1.0}, -np.inf, spec.cap)
        planned = float(len(self.placements))
        result = milp(
            c=self._cost(size, specs),
            constraints=rows.constraint(),
            integrality=np.concatenate([np.ones(fixed), np.zeros(len(specs))]),
            bounds=Bounds(
                np.zeros(size), np.concatenate([np.ones(fixed), np.full(len(specs), planned)])
            ),
            options={"time_limit": _TIME_LIMIT_S},
        )
        if not result.success or result.x is None:
            return None
        chosen: dict[str, str] = {}
        for pair, position in self.index.items():
            if result.x[position] > _HALF:
                for candidate in self.members[pair]:
                    chosen[candidate.placement_id] = pair[1]
        violations = tuple(
            f"{spec.label}: отклонение от квоты на {result.x[fixed + offset]:.0f} посадок"
            for offset, spec in enumerate(specs)
            if result.x[fixed + offset] > _HALF
        )
        return Assignment(
            species_by_placement=dict(sorted(chosen.items())),
            solver=MILP,
            quota_violations=violations,
            notes=tuple(notes),
        )

    def _codes_of(self, structure_id: str) -> list[str]:
        return sorted({c.species.code for c in self.by_structure[structure_id]})

    def _cost(self, size: int, specs: Sequence[_QuotaSpec]) -> np.ndarray:
        cost = np.zeros(size)
        for pair, position in self.index.items():
            cost[position] = -sum(c.score + _FILL_BONUS for c in self.members[pair])
        fixed = len(self.pairs)
        for offset in range(len(specs)):
            cost[fixed + offset] = _QUOTA_PENALTY
        return cost

    def _columns(self, codes: set[str]) -> dict[int, float]:
        """Столбцы задачи с весом «сколько посадок займёт этот вид в этой структуре»."""
        return {
            position: float(len(self.members[pair]))
            for pair, position in self.index.items()
            if pair[1] in codes
        }

    def _quota(self) -> _Quota:
        return _Quota(self.catalog, self.existing, self.params, len(self.placements))

    def _quota_specs(self) -> list[_QuotaSpec]:
        """Мягкие ограничения состава: превышение возможно, но стоит штрафа и попадает в сводку."""
        quota = self._quota()
        specs = [
            _QuotaSpec(f"вид {code}", self._columns({code}), quota.cap_species(code))
            for code in self.codes
        ]
        specs += [
            _QuotaSpec(f"род {genus}", self._columns(codes), quota.cap_genus(genus))
            for genus, codes in sorted(self._grouped("genus").items())
        ]
        specs += [
            _QuotaSpec(f"семейство {family}", self._columns(codes), quota.cap_family(family))
            for family, codes in sorted(self._grouped("family").items())
        ]
        return [spec for spec in specs if spec.columns] + self._conifer_specs()

    def _grouped(self, attribute: str) -> dict[str, set[str]]:
        groups: defaultdict[str, set[str]] = defaultdict(set)
        for code in self.codes:
            species = self.catalog.get(code)
            if species is not None:
                groups[str(getattr(species, attribute))].add(code)
        return groups

    def _conifer_note(self) -> list[str]:
        low_share, _ = self.params.conifer_share
        codes = {c for c in self.codes if c in self.catalog and self.catalog[c].is_conifer}
        if low_share > 0 and not codes:
            return ["доля хвойных не выдержана: допустимых хвойных на участке нет"]
        return []

    def _conifer_specs(self) -> list[_QuotaSpec]:
        low_share, high_share = self.params.conifer_share
        codes = {c for c in self.codes if c in self.catalog and self.catalog[c].is_conifer}
        total = float(len(self.placements))
        entries = self._columns(codes)
        if not entries:
            return []
        specs = []
        if low_share > 0:
            specs.append(
                _QuotaSpec("доля хвойных снизу", entries, low_share * total, at_least=True)
            )
        specs.append(_QuotaSpec("доля хвойных сверху", entries, high_share * total))
        return specs

    # --- жадный запасной путь ---

    def solve_greedy(self) -> Assignment:
        quota = self._quota()
        given_left = dict(self.params.given_assortment)
        given_mode = self.params.assortment_mode == "given"
        chosen: dict[str, str] = {}
        violations: list[str] = []
        order = sorted(self.by_structure, key=lambda s: (-len(self.by_structure[s]), s))
        for structure_id in order:
            members = self.by_structure[structure_id]
            options: defaultdict[str, list[float]] = defaultdict(list)
            for candidate in members:
                options[candidate.species.code].append(candidate.score)
            ranked = sorted(
                options.items(), key=lambda item: (-len(item[1]), -sum(item[1]), item[0])
            )
            fitting = [
                (code, scores)
                for code, scores in ranked
                if quota.fits(code, len(scores))
                and (not given_mode or given_left.get(code, 0) >= len(scores))
            ]
            code = fitting[0][0] if fitting else ranked[0][0]
            if not fitting:
                kind = self.kinds.get(structure_id, SINGLE)
                violations.append(f"{kind} {structure_id}: вид {code} назначен сверх квоты")
            used = 0
            for candidate in members:
                if candidate.species.code == code:
                    chosen[candidate.placement_id] = code
                    used += 1
            quota.take(code, used)
            if given_mode:
                given_left[code] = max(0, given_left.get(code, 0) - used)
        return Assignment(
            species_by_placement=dict(sorted(chosen.items())),
            solver=GREEDY,
            quota_violations=tuple(violations),
            notes=(
                "виды назначены жадным обходом структур по настройке профиля"
                if self.params.assortment_solver == GREEDY
                else "решатель не справился, виды назначены жадным обходом структур",
            ),
        )


class _Quota:
    """Квоты 10-20-30 с учётом уже растущих деревьев: существующая популяция съедает долю.

    Допуск считается от общего числа деревьев - запроектированных и существующих, - поэтому
    вид, которого на улице и так много, новых посадок почти не получает. В целочисленной
    задаче допуск мягкий (превышение стоит штрафа), в жадном пути - жёсткий, и превышение
    там записывается в quota_violations.
    """

    def __init__(
        self,
        catalog: Mapping[str, Species],
        existing: Mapping[str, int],
        params: PlanParams,
        planned: int,
    ) -> None:
        self.catalog = catalog
        self.params = params
        self.total = planned + sum(existing.values())
        self.used_species: defaultdict[str, int] = defaultdict(int)
        self.used_genus: defaultdict[str, int] = defaultdict(int)
        self.used_family: defaultdict[str, int] = defaultdict(int)
        for code, count in existing.items():
            self.used_species[code] += count
            species = catalog.get(code)
            if species is not None:
                self.used_genus[species.genus] += count
                self.used_family[species.family] += count

    def cap_species(self, code: str) -> float:
        return max(0.0, self.params.quota_species * self.total - self.used_species[code])

    def cap_genus(self, genus: str) -> float:
        return max(0.0, self.params.quota_genus * self.total - self.used_genus[genus])

    def cap_family(self, family: str) -> float:
        return max(0.0, self.params.quota_family * self.total - self.used_family[family])

    def fits(self, code: str, count: int) -> bool:
        species = self.catalog.get(code)
        if species is None:
            return self.cap_species(code) >= count
        return (
            self.cap_species(code) >= count
            and self.cap_genus(species.genus) >= count
            and self.cap_family(species.family) >= count
        )

    def take(self, code: str, count: int) -> None:
        self.used_species[code] += count
        species = self.catalog.get(code)
        if species is not None:
            self.used_genus[species.genus] += count
            self.used_family[species.family] += count
