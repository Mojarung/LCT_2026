"""Смысл незнакомого слоя или блока по словам имени (задача 14 плана).

Решение пользователя 25.09.2026: 20 улиц пилота - полигон, цель - новые чертежи; незнакомое не
останавливает прогон, а заменяется самым правдоподобным, газон нового формата всегда газон.
Словарь слов (config/vocabulary.yaml) работает после словаря знаков и правил слоёв, когда те
молчат или спорят. Вывод - предположение по имени, как и правила слоёв: основание (слово)
уходит в отчёт классификации, человек может переназначить класс.

Проектная грамматика - стадия «по проекту» (вопрос 2 пользователя): новое стоит до разделителя
(«Газон за счёт АБ ТР», «ПЧ за газон») и первым в паре заливок «ГЗН-АБ ТР». Снимаемое проектом
(«ВЛИ демонтаж», «газон уничтож») в расчёт не идёт; посадки проектировщика («ГП_Деревья») -
его ответ, а не существующие деревья.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING

from green.application.semantic_names import local_name
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

_SHORT = 3  # слово словаря до трёх букв сравнивается целиком, длиннее - как начало слова
_SPLIT = re.compile(r"[^0-9a-zа-я]+")
_INITIALS = re.compile(r"(?<![0-9a-zа-я])([a-zа-я])\.([a-zа-я])(?![0-9a-zа-я])")
_LETTERS = re.compile(r"^[a-zа-я]+")
_NUMBERED_WORD = re.compile(r"^\d+([a-zа-я]+)$")
_VEGETATION = frozenset({ObjectClass.EXISTING_TREE, ObjectClass.EXISTING_SHRUB})


class Rank(IntEnum):
    """Сила слова: точечный объект конкретнее сети, сеть конкретнее покрытия."""

    POINT = 0
    LINE = 1
    OBJECT = 2
    SURFACE = 3
    BOUNDARY = 4


_FRAME_WORDS = frozenset({"рамк", "border"})


@dataclass(frozen=True, slots=True)
class Inference:
    """Вывод по имени: класс, слово-основание и вид вывода (name, removed, proposed,
    annotation, weak)."""

    object_class: ObjectClass
    word: str
    kind: str = "name"

    @property
    def method(self) -> str:
        return f"inferred_{self.kind}:{self.word}"


@dataclass(frozen=True, slots=True)
class _Hit:
    position: int
    word: str
    object_class: ObjectClass
    rank: Rank


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """Словарь слов: основы -> класс и ранг, служебные слова грамматики."""

    words: Mapping[str, tuple[ObjectClass, Rank]] = field(default_factory=dict)
    phrases: Mapping[str, tuple[ObjectClass, Rank]] = field(default_factory=dict)
    patterns: Sequence[tuple[re.Pattern[str], ObjectClass, Rank]] = ()
    weak: Mapping[str, ObjectClass] = field(default_factory=dict)
    separators: Sequence[str] = ()
    negations: frozenset[str] = frozenset()
    removal: frozenset[str] = frozenset()
    proposed: frozenset[str] = frozenset()
    existing: frozenset[str] = frozenset()
    annotation: frozenset[str] = frozenset()
    annotation_phrases: Sequence[str] = ()
    annotation_patterns: Sequence[re.Pattern[str]] = ()
    fingerprint: str = ""
    # Коды «Классификаторов для информационного моделирования» (Москва, 2024), часть 1 «ТС» и
    # часть 2 «ПО ЗУ»: код -> класс (config/im_classifier.yaml). Код в имени решает раньше слов.
    codes: Mapping[str, ObjectClass] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.words or self.phrases or self.codes)

    def infer(self, *names: str | None) -> Inference | None:
        """Первое имя, по словам которого есть вывод (блок конкретнее слоя).

        Слабый намёк решает, только если ни в одном имени нет сильного слова: «Покрытия» в имени
        контейнерного блока не перебивает «Газон» в имени слоя (аудит Берзарина 16.10.2026).
        """
        for name in names:
            if name and (coded := self.coded(local_name(name))) is not None:
                return coded
        found = [self._infer(local_name(name)) for name in names if name]
        strong = next((item for item in found if item and item.kind != "weak"), None)
        removed = next((item for item in found if item and item.kind == "removed"), None)
        if strong is not None and strong.object_class is ObjectClass.LAWN and removed is not None:
            return removed  # снос в одном имени сильнее газона в другом
        return strong or next((item for item in found if item), None)

    def coded(self, name: str) -> Inference | None:
        """Класс по коду классификатора в имени: «ТС 22 00 01», «ТС_22_00_01», «ТС22000101»,
        «ПО ЗУ 25 10 01», «ПОЗУ-25-10-01». Решает самый длинный код, который есть в словаре."""
        if not self.codes:
            return None
        for match in _CODE.finditer(name.upper()):
            part = "ПО ЗУ" if match.group(1).startswith("П") else "ТС"
            digits = match.group(2)
            groups = re.findall(r"\d+", digits)
            if len(groups) == 1:  # слитно: пары цифр, последняя группа может быть из трёх
                run = groups[0]
                groups = [run[i : i + 2] for i in range(0, len(run) - len(run) % 2, 2)]
                if len(run) % 2:
                    groups[-1] += run[-1]
            # Код не короче трёх групп (раздел, группа, объект): «ТС-16» в чертеже теплосети -
            # номер камеры, а не раздел «Канализация ливневая».
            for size in range(len(groups), _CODE_MIN_GROUPS - 1, -1):
                code = " ".join([part, *groups[:size]])
                if code in self.codes:
                    return Inference(self.codes[code], code, "classifier")
        return None

    def _infer(self, name: str) -> Inference | None:
        text = normalize(name)
        tokens = text.split()
        if not tokens:
            return None
        if (word := self._annotation(text, tokens)) and not self._boundary(text, word):
            return Inference(ObjectClass.IGNORE, word, "annotation")
        head = self._head(name, tokens)
        hits = self._hits(" ".join(head), head)
        negated, cut = self._removed(head, hits)
        kept = [hit for hit in hits if hit.position not in negated | cut]
        if kept:
            return self._decide(kept, tokens)
        return self._leftover(head, negated=bool(negated))

    def _leftover(self, head: list[str], *, negated: bool) -> Inference | None:
        """Слов-объектов не осталось. Снимаемое проектом в расчёт не идёт; отрицание («не
        газон») смысла не даёт - решает осторожная замена по геометрии, чтобы газон вокруг не
        «протёк» внутрь; иначе - слабый намёк."""
        if negated:
            return None
        if removal := next((w for w in (_match(t, self.removal) for t in head) if w), None):
            return Inference(ObjectClass.IGNORE, removal, "removed")
        for token in _aliases(head):
            if (word := _match_word(token, self.weak)) is not None:
                return Inference(self.weak[word], word, "weak")
        return None

    def _service(self) -> frozenset[str]:
        return self.removal | self.proposed | self.existing | self.negations

    def _boundary(self, text: str, word: str) -> bool:
        """Фраза границы работ сильнее только слов рамки: «РАМКА_ГРАНИЦА_УЧАСТКА», «SITE_BORDER»
        у других команд - граница участка (17.10.2026), а «Подписи границы работ» - подписи."""
        if word not in _FRAME_WORDS:
            return False
        return any(
            kind is ObjectClass.WORK_BOUNDARY and _has_phrase(text, phrase)
            for phrase, (kind, _) in self.phrases.items()
        )

    def _annotation(self, text: str, tokens: list[str]) -> str | None:
        for phrase in self.annotation_phrases:
            if _has_phrase(text, phrase):
                return phrase
        for pattern in self.annotation_patterns:
            if found := pattern.search(text):
                return found.group()
        for token in _aliases(tokens):
            if (word := _match(token, self.annotation)) is not None:
                return word
        return None

    def _head(self, name: str, tokens: list[str]) -> list[str]:
        """Слова нового состояния: первая часть пары «A-B» или всё до разделителя."""
        parts = [normalize(part).split() for part in name.split("-")]
        with_words = [part for part in parts if self._hits(" ".join(part), part)]
        if len(with_words) >= 2:  # noqa: PLR2004 - пара материалов
            return with_words[0]
        for position in range(1, len(tokens)):
            for separator in self.separators:
                size = len(separator.split())
                if " ".join(tokens[position : position + size]) == separator:
                    # Заменяемое («за счёт газона») класса не даёт, даже если в новом
                    # (до разделителя) есть только слабый намёк или нет слов вовсе.
                    return tokens[:position]
        return tokens

    def _hits(self, text: str, tokens: list[str]) -> list[_Hit]:
        hits = []
        taken: set[int] = set()
        for phrase, (kind, rank) in self.phrases.items():
            if _has_phrase(text, phrase):
                start = _phrase_position(tokens, phrase)
                hits.append(_Hit(start, phrase, kind, rank))
                # Фраза занимает все свои слова: «край дороги» не даёт ещё и «дорогу», и снос
                # («_демонтаж») снимает фразу как одно слово (ревью 17.10.2026).
                taken.update(range(start, start + len(phrase.split())))
        for pattern, kind, rank in self.patterns:
            if pattern.search(text):
                hits.append(_Hit(0, pattern.pattern, kind, rank))
        for position, token in enumerate(tokens):
            if position in taken:
                continue
            word = _name_word(token, self.words)
            if word is not None:
                kind, rank = self.words[word]
                hits.append(_Hit(position, word, kind, rank))
        return sorted(hits, key=lambda hit: hit.position)

    def _removed(self, tokens: list[str], hits: list[_Hit]) -> tuple[set[int], set[int]]:
        """Позиции слов, снятых отрицанием («без газона» - следующее слово) и сносом («газон
        под демонтаж», «ВЛИ демонтаж» - ближайшее слово-объект с любой стороны)."""
        positions = sorted(hit.position for hit in hits)
        negated, cut = set(), set()
        for position, token in enumerate(tokens):
            if _match(token, self.negations) is not None and position + 1 in positions:
                negated.add(position + 1)
            if _match(token, self.removal) is not None and positions:
                cut.add(min(positions, key=lambda hit: (abs(hit - position), hit > position)))
        return negated, cut

    def _decide(self, hits: list[_Hit], tokens: list[str]) -> Inference:
        best = min(hit.rank for hit in hits)
        top = [hit for hit in hits if hit.rank == best]
        if best is Rank.SURFACE:
            chosen = top[-1]
        else:
            known = [hit for hit in top if hit.object_class is not ObjectClass.UTILITY_UNKNOWN]
            chosen = (known or top)[0]
        if chosen.object_class in _VEGETATION:
            marks = {_match(token, self._service()) for token in _aliases(tokens)}
            proposed = next((w for w in marks if w in self.proposed), None)
            existing = any(w in self.existing for w in marks if w)
            cut = next((w for w in marks if w in self.removal), None)
            if cut:
                return Inference(ObjectClass.IGNORE, cut, "removed")
            if proposed and not existing:
                return Inference(ObjectClass.IGNORE, proposed, "proposed")
        return Inference(chosen.object_class, chosen.word)


_CODE_MIN_GROUPS = 3
_CODE = re.compile(r"(?<![А-ЯA-Z])(ТС|ПО[\s_.\-]*ЗУ)[\s_.\-]*(\d{2}[\d\s_.\-]*)")


def normalize(name: str) -> str:
    """Строчные, ё -> е, «а.б» -> «аб», разделители -> пробел."""
    text = unicodedata.normalize("NFC", name).casefold().replace("ё", "е")
    text = _INITIALS.sub(r"\1\2", text)
    return " ".join(_SPLIT.split(text)).strip()


def _aliases(tokens: Iterable[str]) -> list[str]:
    """Слова и буквенные части слов из букв и цифр («бр100» -> «бр»)."""
    result = []
    for token in tokens:
        result.append(token)
        letters = _LETTERS.match(token)
        if letters and letters.group() != token:
            result.append(letters.group())
    return result


def _matches(token: str, word: str) -> bool:
    return token == word if len(word) <= _SHORT else token.startswith(word)


def _match(token: str, words: Iterable[str]) -> str | None:
    """Самое длинное слово словаря, которым начинается token (короткие - целиком)."""
    found = [word for word in words if _matches(token, word)]
    return max(found, key=len) if found else None


def _match_word(token: str, words: Mapping[str, object]) -> str | None:
    return _match(token, words.keys())


def _name_word(token: str, words: Mapping[str, object]) -> str | None:
    word = _match_word(token, words)
    # Only a complete dictionary word, not an arbitrary substring of a code.
    if word is None and (numbered := _NUMBERED_WORD.fullmatch(token)) and numbered[1] in words:
        word = numbered[1]
    if word is None and (letters := _LETTERS.match(token)) and letters.group() != token:
        word = _match_word(letters.group(), words)
    return word


def _has_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![0-9a-zа-я]){re.escape(phrase)}", text) is not None


def _phrase_position(tokens: list[str], phrase: str) -> int:
    first = phrase.split(maxsplit=1)[0]
    return next((i for i, token in enumerate(tokens) if token.startswith(first)), 0)


def build_vocabulary(data: Mapping[str, object], fingerprint: str = "") -> Vocabulary:
    """Словарь из разобранного config/vocabulary.yaml."""
    words: dict[str, tuple[ObjectClass, Rank]] = {}
    phrases: dict[str, tuple[ObjectClass, Rank]] = {}
    patterns: list[tuple[re.Pattern[str], ObjectClass, Rank]] = []
    classes: Mapping[str, Mapping[str, object]] = data.get("classes", {})  # ty: ignore[invalid-assignment]
    for value, entry in classes.items():
        kind, rank = ObjectClass(value), Rank[str(entry["rank"]).upper()]
        for word in entry.get("words", ()):  # ty: ignore[not-iterable]
            words[normalize(str(word))] = (kind, rank)
        for phrase in entry.get("phrases", ()):  # ty: ignore[not-iterable]
            phrases[normalize(str(phrase))] = (kind, rank)
        patterns.extend(
            (re.compile(str(pattern)), kind, rank)
            for pattern in entry.get("patterns", ())  # ty: ignore[not-iterable]
        )
    annotation: Mapping[str, Sequence[str]] = data.get("annotation", {})  # ty: ignore[invalid-assignment]

    def listed(key: str) -> frozenset[str]:
        return frozenset(normalize(str(w)) for w in data.get(key, ()))  # ty: ignore[not-iterable]

    weak: Mapping[str, str] = data.get("weak", {})  # ty: ignore[invalid-assignment]
    return Vocabulary(
        words=words,
        phrases=phrases,
        patterns=tuple(patterns),
        weak={normalize(k): ObjectClass(v) for k, v in weak.items()},
        separators=tuple(normalize(str(s)) for s in data.get("separators", ())),  # ty: ignore[not-iterable]
        negations=listed("negations"),
        removal=listed("removal"),
        proposed=listed("proposed"),
        existing=listed("existing"),
        annotation=frozenset(normalize(str(w)) for w in annotation.get("words", ())),
        annotation_phrases=tuple(normalize(str(p)) for p in annotation.get("phrases", ())),
        annotation_patterns=tuple(re.compile(str(p)) for p in annotation.get("patterns", ())),
        fingerprint=fingerprint,
    )
