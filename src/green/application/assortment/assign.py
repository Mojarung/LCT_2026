"""Назначение видов: одна задача оптимизации вместо обхода посадок по очереди.

Жадный обход обделяет тех, кто идёт последним: первые ряды забирают лучшие виды, а квоты
разнообразия («не больше 10% одного вида») при таком обходе почти всегда ломаются на
хвосте. Поэтому виды назначаются всем посадкам сразу целочисленной задачей: переменная
x[посадка, вид] и переменная y[структура, вид] для однородности рядов и групп.

Ограничения: одна посадка - не больше одного вида; вид в структуре учитывается через y;
ряд - один вид, группа - не больше group_max_species; квоты 10-20-30 по виду, роду и
семейству с учётом существующих деревьев; доля хвойных в заданном коридоре. Цель -
максимум суммы оценок плюс премия за каждую заполненную посадку минус штраф за пестроту.

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

from green.application.assortment.structures import ROW

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from green.application.assortment.structures import Structure
    from green.application.params import PlanParams
    from green.domain.planting import Species

MILP = "milp"
GREEDY = "greedy"
_TIME_LIMIT_S = 60.0
_FILL_BONUS = 1.0  # заполнить посадку всегда выгоднее, чем оставить её без вида
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
        self.sizes = {s.structure_id: len(s.placement_ids) for s in structures}
        self.by_structure: defaultdict[str, list[Candidate]] = defaultdict(list)
        for candidate in self.candidates:
            self.by_structure[candidate.structure_id].append(candidate)
        self.floor = self._floor()
        self.x_index = {(c.placement_id, c.species.code): i for i, c in enumerate(self.candidates)}
        self.y_pairs = sorted(
            {
                (c.structure_id, c.species.code)
                for c in self.candidates
                if self.sizes.get(c.structure_id, 1) >= _MIN_STRUCTURE
            }
        )
        self.y_index = {pair: len(self.x_index) + i for i, pair in enumerate(self.y_pairs)}

    # --- целочисленная задача ---

    def solve_milp(self) -> Assignment | None:
        size = len(self.x_index) + len(self.y_index)
        rows = _Rows(size)
        notes: list[str] = []
        self._placement_rows(rows)
        self._structure_rows(rows)
        if self.params.assortment_mode == "given":
            for code, count in sorted(self.params.given_assortment.items()):
                rows.add(self._columns({code}), 0.0, float(count))
            notes.append("режим заданного ассортимента: квоты разнообразия не применяются")
        else:
            notes += self._quota_rows(rows)
            notes += self._conifer_rows(rows)
        result = milp(
            c=self._cost(size),
            constraints=rows.constraint(),
            integrality=np.ones(size),
            bounds=Bounds(0, 1),
            options={"time_limit": _TIME_LIMIT_S},
        )
        if not result.success or result.x is None:
            return None
        chosen = {
            placement: code
            for (placement, code), index in self.x_index.items()
            if result.x[index] > _HALF
        }
        return Assignment(
            species_by_placement=dict(sorted(chosen.items())), solver=MILP, notes=tuple(notes)
        )

    def _cost(self, size: int) -> np.ndarray:
        cost = np.zeros(size)
        for candidate in self.candidates:
            index = self.x_index[(candidate.placement_id, candidate.species.code)]
            cost[index] = -(candidate.score + _FILL_BONUS)
        for index in self.y_index.values():
            cost[index] = self.params.structure_penalty
        return cost

    def _placement_rows(self, rows: _Rows) -> None:
        by_placement: defaultdict[str, dict[int, float]] = defaultdict(dict)
        for (placement, _), index in self.x_index.items():
            by_placement[placement][index] = 1.0
        for placement in self.placements:
            rows.add(by_placement[placement], 0.0, 1.0)

    def _structure_rows(self, rows: _Rows) -> None:
        for structure_id, code in self.y_pairs:
            entries = {
                self.x_index[(c.placement_id, code)]: 1.0
                for c in self.by_structure[structure_id]
                if c.species.code == code
            }
            entries[self.y_index[(structure_id, code)]] = -float(self.sizes[structure_id])
            rows.add(entries, -np.inf, 0.0)
        for structure_id in sorted({s for s, _ in self.y_pairs}):
            entries = {
                self.y_index[(structure_id, code)]: 1.0
                for s, code in self.y_pairs
                if s == structure_id
            }
            limit = (
                1.0
                if self.kinds.get(structure_id, ROW) == ROW
                else float(self.params.group_max_species)
            )
            rows.add(entries, 0.0, limit)

    def _columns(self, codes: set[str]) -> dict[int, float]:
        return {index: 1.0 for (_, code), index in self.x_index.items() if code in codes}

    def _floor(self) -> int:
        """Нижний порог допуска: сколько посадок вид обязан иметь право занять.

        Он держит две вещи: структура должна помещаться в один вид, а доступного
        разнообразия должно хватать, чтобы занять все посадки. Второе считается по видам,
        родам и семействам, потому что квота семейства сужает ёмкость сильнее видовой:
        шесть видов, из которых два хвойных одного семейства, покрывают меньше, чем
        кажется по числу видов. Виды, у которых допуск уже съеден существующими
        деревьями, в расчёт не идут.
        """
        largest = max((self.sizes.get(s, 1) for s in self.by_structure), default=1)
        planned = len(self.placements)
        base = _Quota(self.catalog, self.existing, self.params, planned, largest)
        usable = [code for code in self.codes if base.cap_species(code) > 0]
        if not usable:
            return largest
        known = [self.catalog[code] for code in usable if code in self.catalog]
        counts = [len(usable), len({s.genus for s in known}), len({s.family for s in known})]
        return max(largest, *(-(-planned // n) for n in counts if n))

    def _quota(self) -> _Quota:
        return _Quota(self.catalog, self.existing, self.params, len(self.placements), self.floor)

    def _quota_rows(self, rows: _Rows) -> list[str]:
        quota = self._quota()
        for code in self.codes:
            rows.add(self._columns({code}), 0.0, quota.cap_species(code))
        for genus, codes in sorted(self._grouped("genus").items()):
            rows.add(self._columns(codes), 0.0, quota.cap_genus(genus))
        for family, codes in sorted(self._grouped("family").items()):
            rows.add(self._columns(codes), 0.0, quota.cap_family(family))
        if quota.raised:
            raised = (
                f"квота вида поднята до {self.floor} посадок: иначе структуру нельзя "
                "выдержать в одном виде или посадок больше, чем позволяет доля "
                "при доступных видах"
            )
            return [raised]
        return []

    def _grouped(self, attribute: str) -> dict[str, set[str]]:
        groups: defaultdict[str, set[str]] = defaultdict(set)
        for code in self.codes:
            species = self.catalog.get(code)
            if species is not None:
                groups[str(getattr(species, attribute))].add(code)
        return groups

    def _conifer_rows(self, rows: _Rows) -> list[str]:
        low_share, high_share = self.params.conifer_share
        codes = {c for c in self.codes if c in self.catalog and self.catalog[c].is_conifer}
        entries = self._columns(codes)
        total = len(self.placements)
        if not entries:
            if low_share > 0:
                return ["доля хвойных не выдержана: допустимых хвойных на участке нет"]
            return []
        quota = self._quota()
        reachable = len({placement for (placement, code) in self.x_index if code in codes})
        capacity = min(float(reachable), sum(quota.cap_species(code) for code in sorted(codes)))
        low = low_share * total
        notes: list[str] = []
        if capacity + _EPS < low:
            notes.append(
                f"нижняя граница доли хвойных снята: мест под хвойные {capacity:.0f} "
                f"при требуемых {low:.0f}"
            )
            low = 0.0
        rows.add(entries, low, high_share * total)
        return notes

    # --- жадный запасной путь ---

    def solve_greedy(self) -> Assignment:
        quota = self._quota()
        given_left = dict(self.params.given_assortment)
        given_mode = self.params.assortment_mode == "given"
        chosen: dict[str, str] = {}
        violations: list[str] = []
        for structure_id in sorted(self.by_structure, key=lambda s: (-self.sizes.get(s, 1), s)):
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
                violations.append(
                    f"структура {structure_id}: вид {code} назначен с нарушением квоты"
                )
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

    У квоты есть нижний порог. Без него квота противоречит однородности ряда: при 30
    посадках 10% - это три дерева, а ряд из десяти требует десяти одного вида, и солвер
    оставил бы семь посадок пустыми. Поэтому допуск не опускается ниже размера самой
    крупной структуры и ниже доли, которой хватает, чтобы занять все посадки доступными
    видами. Существующие деревья вычитаются уже из поднятого допуска, поэтому вид,
    которого на улице и так много, всё равно не назначается.
    """

    def __init__(
        self,
        catalog: Mapping[str, Species],
        existing: Mapping[str, int],
        params: PlanParams,
        planned: int,
        floor: int = 1,
    ) -> None:
        self.catalog = catalog
        self.params = params
        self.floor = float(floor)
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
        allowed = max(self.params.quota_species * self.total, self.floor)
        return max(0.0, allowed - self.used_species[code])

    def cap_genus(self, genus: str) -> float:
        allowed = max(self.params.quota_genus * self.total, self.floor)
        return max(0.0, allowed - self.used_genus[genus])

    def cap_family(self, family: str) -> float:
        allowed = max(self.params.quota_family * self.total, self.floor)
        return max(0.0, allowed - self.used_family[family])

    @property
    def raised(self) -> bool:
        """Порог оказался выше квоты: доли в сводке будут больше заявленных."""
        return self.floor > self.params.quota_species * self.total

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
