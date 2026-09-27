"""Веса индекса качества по суждениям экспертов: метод анализа иерархий (Саати).

Весов индекса ни один акт не задаёт, и подобрать их «перебором» не к чему - нет эталонных
оценок. Методичка OECD/JRC по составным индексам прямо называет веса ценностным суждением
(«weights are essentially value judgements», Handbook on Constructing Composite Indicators,
2008, с. 31) и предлагает получать их от экспертов. Здесь - её процедура:

- иерархия в два уровня: четыре группы слагаемых, внутри группы - слагаемые (OECD, с. 31:
  равные веса слагаемых при разных размерах групп смещают веса групп);
- эксперт сравнивает пары по шкале Саати 1-9 (Saaty 2008, табл. 1);
- вес - главный собственный вектор матрицы, согласованность - отношение CR < 0,1
  (OECD, с. 97-98, со ссылкой на Saaty 1980);
- суждения нескольких экспертов сводятся поэлементным геометрическим средним (AIJ, Forman,
  Peniwati 1998), итоговый вес слагаемого = вес группы x вес внутри группы.

Источники и статусы проверки - docs/plans/2026-09-22-quality-literature.md, п. 8.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from numpy.typing import NDArray

# Группы индекса (docs/plans/2026-09-22-quality-literature.md, п. 8.1). Порядок внутри группы
# задаёт порядок строк и столбцов матрицы суждений.
GROUPS: dict[str, tuple[str, ...]] = {
    "reliability": ("fit", "category", "margin"),
    "functions": ("canopy", "dust", "tiers"),
    "composition": ("diversity", "rows", "season"),
    "volume": ("density",),
}
GROUP_TITLES = {
    "reliability": "Надёжность: выживет ли посадка и устоит ли план при проверке на месте",
    "functions": "Функции: что посадки дают улице (тень, пыль, ярусы)",
    "composition": "Состав: устойчивость к вредителям и облик",
    "volume": "Объём: не мало ли посадок против МГСН В.1",
}
# Случайный индекс согласованности Саати для матриц порядка n.
RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32}
CR_LIMIT = 0.1
_SCALE_MAX = 9.0


@dataclass(frozen=True, slots=True)
class Priorities:
    weights: tuple[float, ...]
    cr: float

    @property
    def consistent(self) -> bool:
        return self.cr < CR_LIMIT


def matrix(size: int, upper: Sequence[float]) -> NDArray[np.float64]:
    """Матрица парных сравнений из верхнего треугольника, построчно.

    Для 4 групп upper = [a12, a13, a14, a23, a24, a34]: a12 = 3 значит «первое важнее второго
    в 3 раза», 1/3 - наоборот. Нижний треугольник - обратные величины.
    """
    expected = size * (size - 1) // 2
    if len(upper) != expected:
        raise ValueError(f"для {size} критериев нужно {expected} суждений, дано {len(upper)}")
    result = np.ones((size, size), dtype=np.float64)
    values = iter(upper)
    for i in range(size):
        for j in range(i + 1, size):
            value = float(next(values))
            if not 1 / _SCALE_MAX <= value <= _SCALE_MAX:
                raise ValueError(f"суждение {value} вне шкалы Саати 1/9..9")
            result[i, j], result[j, i] = value, 1 / value
    return result


def priorities(judgements: NDArray[np.float64]) -> Priorities:
    """Главный собственный вектор и отношение согласованности CR = CI / RI."""
    size = judgements.shape[0]
    if size == 1:
        return Priorities((1.0,), 0.0)
    values, vectors = np.linalg.eig(judgements)
    lead = int(np.argmax(values.real))
    vector = np.abs(vectors[:, lead].real)
    weights = vector / vector.sum()
    ci = (values[lead].real - size) / (size - 1)
    ri = RANDOM_INDEX.get(size, 1.41)
    return Priorities(tuple(float(w) for w in weights), float(ci / ri) if ri else 0.0)


def aggregate(matrices: Sequence[NDArray[np.float64]]) -> NDArray[np.float64]:
    """Сведение экспертов (AIJ): поэлементное геометрическое среднее матриц."""
    stacked = np.stack(matrices)
    return np.exp(np.log(stacked).mean(axis=0))


@dataclass(frozen=True, slots=True)
class ExpertWeights:
    name: str
    groups: Priorities
    within: Mapping[str, Priorities]
    terms: Mapping[str, float]

    @property
    def consistent(self) -> bool:
        return self.groups.consistent and all(p.consistent for p in self.within.values())


def expert_weights(name: str, judgements: Mapping[str, Sequence[float]]) -> ExpertWeights:
    """Веса слагаемых по анкете одного эксперта: группы и три группы изнутри."""
    names = list(GROUPS)
    groups = priorities(matrix(len(names), judgements["groups"]))
    within = {
        group: priorities(matrix(len(keys), judgements.get(group, ())))
        for group, keys in GROUPS.items()
        if len(keys) > 1
    }
    return ExpertWeights(name, groups, within, _terms(groups, within))


def panel_weights(forms: Mapping[str, Mapping[str, Sequence[float]]]) -> ExpertWeights:
    """Веса по всей панели: матрицы экспертов сводятся геометрическим средним."""
    names = list(GROUPS)
    groups = priorities(aggregate([matrix(len(names), f["groups"]) for f in forms.values()]))
    within = {
        group: priorities(aggregate([matrix(len(keys), f.get(group, ())) for f in forms.values()]))
        for group, keys in GROUPS.items()
        if len(keys) > 1
    }
    return ExpertWeights("панель", groups, within, _terms(groups, within))


def _terms(groups: Priorities, within: Mapping[str, Priorities]) -> dict[str, float]:
    terms: dict[str, float] = {}
    for weight, (group, keys) in zip(groups.weights, GROUPS.items(), strict=True):
        inner = within[group].weights if group in within else (1.0,)
        for key, share in zip(keys, inner, strict=True):
            terms[key] = round(weight * share, 4)
    return terms


__all__ = [
    "CR_LIMIT",
    "GROUPS",
    "GROUP_TITLES",
    "ExpertWeights",
    "Priorities",
    "aggregate",
    "expert_weights",
    "matrix",
    "panel_weights",
    "priorities",
]
