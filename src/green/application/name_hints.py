"""Подсказки LLM по именам слоёв, которые не поняли правила, словарь и модель имён.

Только подсказка (пользователь, 17.10.2026): класс объекта и план от ответа модели не зависят.
Ответ показывается в отчёте классификации (name_hints.json) рядом с тем, как сервис решил сам,
чтобы человек мог назначить класс слою через layer_classes и перезапустить. Спрашиваются только
имена со смыслом: слой «0» и контейнеры внешних ссылок не несут его, их не исправит никакая
модель имён. Опыт E1 (docs/plans/2026-10-16-ml-experiments.md): qwen3:8b узнаёт 87% чужих
имён, но путает газон и границу работ - поэтому и подсказка, а не решение.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from green.application.name_model import name_key
from green.domain.objects import ObjectClass

if TYPE_CHECKING:
    from green.application.classification import ClassificationReport
    from green.application.ports import LayerNameHinter

# Как объект получил класс, если имя ничего не сказало: по одной геометрии или по слабому намёку.
_ASK_METHODS = frozenset({"assumed_geometry", "inferred_weak"})
MIN_CONFIDENCE = 0.6
_MAY_BE_IGNORED = frozenset({ObjectClass.CONTOUR.value, ObjectClass.OBSTACLE.value})
DEFAULT_LIMIT = 60
_LETTERS = re.compile(r"[a-zа-яё]{3,}", re.IGNORECASE)
# Имена без смысла: «0», служебные слои, контейнеры внешних ссылок и уровни MicroStation.
_MEANINGLESS = re.compile(
    r"^(?:0|defpoints|level \d+)$|вн\.?\s*ссыл|внешн\w* ссыл|xref", re.IGNORECASE
)
ALLOWED = frozenset(
    c.value
    for c in ObjectClass
    if c not in {ObjectClass.UNKNOWN, ObjectClass.CONTOUR} and not c.value.startswith("territory")
) | {ObjectClass.CONTOUR.value}


@dataclass(frozen=True, slots=True)
class HintCandidate:
    name: str
    features: int
    current: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NameHint:
    """Предположение модели о классе слоя; в план не идёт."""

    name: str
    features: int
    current: dict[str, int]
    suggestion: str
    confidence: float
    model: str


def hint_candidates(report: ClassificationReport) -> list[HintCandidate]:
    """Имена слоёв и блоков, решённые одной геометрией или слабым намёком, со смыслом в имени;
    больше объектов - раньше."""
    features: Counter[str] = Counter()
    current: dict[str, Counter[str]] = {}
    for group in report.groups:
        if group.evidence.method.split(":", 1)[0] not in _ASK_METHODS:
            continue
        name = name_key(group.layer, group.block)
        local = group.layer.split("$0$")[-1].split("|")[-1].strip()
        if _MEANINGLESS.search(local) or _MEANINGLESS.search(group.layer):
            continue
        if not _LETTERS.search(name):
            continue
        features[name] += group.features
        current.setdefault(name, Counter())[group.object_class.value] += group.features
    return [
        HintCandidate(name, n, dict(current[name].most_common()))
        for name, n in features.most_common()
    ]


def name_hints(
    report: ClassificationReport, hinter: LayerNameHinter, *, limit: int = DEFAULT_LIMIT
) -> tuple[NameHint, ...]:
    """Спросить модель о кандидатах (не больше limit имён) и оставить ответы, которые уверенно
    предлагают другой класс из списка сервиса."""
    candidates = hint_candidates(report)[:limit]
    if not candidates:
        return ()
    answers = hinter.suggest([c.name for c in candidates])
    hints = []
    for candidate, (suggestion, confidence) in zip(candidates, answers, strict=True):
        if suggestion not in ALLOWED or confidence < MIN_CONFIDENCE:
            continue
        main = next(iter(candidate.current), None)
        if suggestion == main:
            continue
        # «Оформление» снимает объект с ограничений: подсказка допустима только для линий без
        # смысла и препятствий по геометрии, не для сети или покрытия (qwen3:8b отправлял туда
        # слои силового кабеля, живой прогон 17.10.2026).
        if suggestion == ObjectClass.IGNORE.value and main not in _MAY_BE_IGNORED:
            continue
        hints.append(
            NameHint(
                candidate.name,
                candidate.features,
                candidate.current,
                suggestion,
                round(min(max(confidence, 0.0), 1.0), 2),
                hinter.model,
            )
        )
    return tuple(hints)
