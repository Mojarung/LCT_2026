"""Класс объекта по похожему имени слоя: третья ступень после правил и словаря слов.

Обычно учат классификатор имён слоёв (сторонний вход: TF-IDF + kNN по 19,5 тыс. имён). Здесь то
же без внешних библиотек: имена слоёв, класс которых решило правило имени на 19 улицах пилота
(config/name_model.json, tools/build_name_model.py), раскладываются в символьные триграммы, у
незнакомого имени ищутся ближайшие по косинусу, класс решает взвешенное голосование. Модель
предлагает класс, только если уверена (MIN_SIMILARITY, MIN_SHARE), и никогда не назначает
класс, который расширяет зону посадки (газон, граница работ): правило безопасности сторонний вход.
Основание в classification.json - `model:<класс>`, с долей голосов и ближайшим именем.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from green.application.semantic_names import base_name, local_name
from green.domain.objects import ObjectClass

MIN_SIMILARITY = 0.6  # косинус ближайшего обучающего имени
MIN_SHARE = 0.7  # доля голосов за класс среди соседей
NEIGHBOURS = 5
# Модель не расширяет зону посадки и не решает место: такие классы только по правилам и словам.
# ignore тоже расширяет: объект выпадает из ограничений (ревью 16.10.2026).
NEVER = frozenset(
    {
        ObjectClass.IGNORE,
        ObjectClass.LAWN,
        ObjectClass.WORK_BOUNDARY,
        ObjectClass.CONTOUR,
        ObjectClass.UNKNOWN,
        ObjectClass.TERRITORY_STREET,
        ObjectClass.TERRITORY_YARD,
        ObjectClass.TERRITORY_SQUARE,
        ObjectClass.TERRITORY_PARK,
    }
)
# Имя, в котором меньше трёх букв («0», «12», «0 RL 2.8.1.2»), смысла не несёт: цифры
# заменяются на #, и косинус коротких векторов случайно высок (слой «0» получал борт от
# «БР 1000 300 150», 16.10.2026).
MIN_LETTERS = 3
_LETTERS = re.compile(r"[a-zа-яё]", re.IGNORECASE)
_DIGITS = re.compile(r"\d+")
_SPACES = re.compile(r"[\s_\-.|$]+")


def name_key(layer: str, block: str | None) -> str:
    """Имя для модели: локальное имя слоя и базовое имя блока (без префикса ссылки и номеров)."""
    named = "" if block is None or block.startswith("*") else base_name(local_name(block))
    return f"{local_name(layer)} {named}".strip()


def _grams(name: str) -> Counter[str]:
    text = _SPACES.sub(" ", _DIGITS.sub("#", name.lower().replace("ё", "е"))).strip()
    padded = f" {text} "
    return Counter(padded[i : i + 3] for i in range(len(padded) - 2))


@dataclass(frozen=True, slots=True)
class Guess:
    object_class: ObjectClass
    share: float
    similarity: float
    nearest: str

    @property
    def method(self) -> str:
        return f"model:{self.object_class.value} p={self.share:.2f} ~{self.nearest}"


@dataclass(slots=True)
class NameModel:
    """Обучающие имена и их классы; пустая модель ничего не предлагает."""

    names: tuple[str, ...] = ()
    classes: tuple[ObjectClass, ...] = ()
    _vectors: list[tuple[dict[str, int], float]] = field(default_factory=list, repr=False)
    _postings: dict[str, list[int]] = field(default_factory=dict, repr=False)
    _cache: dict[str, Guess | None] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        postings: defaultdict[str, list[int]] = defaultdict(list)
        for i, name in enumerate(self.names):
            grams = dict(_grams(name))
            self._vectors.append((grams, math.sqrt(sum(v * v for v in grams.values()))))
            for gram in grams:
                postings[gram].append(i)
        self._postings = dict(postings)

    def __bool__(self) -> bool:
        return bool(self.names)

    def guess(self, layer: str, block: str | None) -> Guess | None:
        key = name_key(layer, block)
        if key not in self._cache:
            self._cache[key] = self._guess(key)
        return self._cache[key]

    def _guess(self, key: str) -> Guess | None:
        if len(_LETTERS.findall(key)) < MIN_LETTERS:
            return None
        grams = _grams(key)
        norm = math.sqrt(sum(v * v for v in grams.values()))
        if not norm:
            return None
        dots: Counter[int] = Counter()
        for gram, count in grams.items():
            for i in self._postings.get(gram, ()):
                dots[i] += count * self._vectors[i][0][gram]
        scored = sorted(
            ((dot / (norm * self._vectors[i][1]), i) for i, dot in dots.items()), reverse=True
        )[:NEIGHBOURS]
        if not scored or scored[0][0] < MIN_SIMILARITY:
            return None
        votes: defaultdict[ObjectClass, float] = defaultdict(float)
        for similarity, i in scored:
            votes[self.classes[i]] += similarity
        winner, weight = max(votes.items(), key=lambda item: item[1])
        share = weight / sum(votes.values())
        if share < MIN_SHARE or winner in NEVER:
            return None
        best = next(i for _, i in scored if self.classes[i] is winner)
        top = max(s for s, i in scored if self.classes[i] is winner)
        return Guess(winner, share, top, self.names[best])
