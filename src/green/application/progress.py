"""Ход прогона для человека: этапы, их доля во времени и оценка остатка.

Веса - доли типичного прогона по DXF, снятые с `timings_ms` в `run_manifest.json` последних
прогонов (Камчатская 39,5 МБ - 98 с, Кустанайская 19,3 МБ с комплектом - 136 с, генплан
Берзарина 76 МБ - 127-200 с, встроенный фрагмент 3,7 МБ - 9 с). Априорная длительность
считается по размеру исходника, а после каждого завершённого этапа замещается фактической:
оценка «сколько осталось» честна ровно настолько, насколько предсказуем следующий этап, и
чем дальше прогон, тем меньше в ней догадки.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime

    from green.application.results import RunProgress


@dataclass(frozen=True, slots=True)
class Stage:
    id: str
    title: str
    # Доля во времени прогона по DXF без конвертации и склейки; у этих двух вес задан
    # относительно такого прогона (конвертация DWG Берзарина - ещё половина сверху).
    weight: float


STAGES: tuple[Stage, ...] = (
    Stage("convert", "Конвертация DWG в DXF", 0.55),
    Stage("merge", "Склейка комплекта чертежей", 0.25),
    Stage("load_config", "Нормы и каталог видов", 0.01),
    Stage("read", "Чтение чертежа", 0.29),
    Stage("classify", "Разбор подосновы", 0.06),
    Stage("basemap", "Подоснова для карты", 0.03),
    Stage("place", "Размещение посадок", 0.14),
    Stage("assort", "Подбор ассортимента", 0.03),
    Stage("shrub_groups", "Группы кустарников", 0.04),
    Stage("surface", "Карта покрытий: где грунт, где твёрдое", 0.03),
    Stage("shrub_rows", "Ряд кустарника у борта", 0.01),
    Stage("understory", "Кустарник под кронами", 0.01),
    Stage("shrub_fill", "Группы кустарника на газоне", 0.02),
    Stage("quotas", "Шаг ям и квоты кустарника", 0.01),
    Stage("validate_plan", "Независимая проверка плана", 0.03),
    Stage("quality", "Индекс качества и ценность посадок", 0.01),
    Stage("refine", "Сдвиг слабых мест от ближайшей нормы", 0.01),
    Stage("lawns", "Газоны на свободном грунте", 0.01),
    Stage("effect", "Баланс озеленения «было - стало»", 0.01),
    Stage("explain", "Объяснения по нормам", 0.01),
    Stage("write_dxf", "Запись DXF", 0.18),
    Stage("verify", "Сверка целостности исходника", 0.19),
    Stage("artifacts", "Отчёты и выгрузки", 0.02),
)
BY_ID = {stage.id: stage for stage in STAGES}
# Вес этапа, которого нет в таблице: новый этап сценария не ломает оценку хода.
_UNKNOWN_WEIGHT = 0.01
# Этапы, которые есть не у каждого прогона.
OPTIONAL = frozenset({"convert", "merge"})

SECONDS_PER_MB = 2.4
MIN_PRIOR_S = 6.0
# Внутри этапа полоса не доходит до его края: конец этапа объявляет секундомер, а не часы.
STAGE_CAP = 0.97
# Полоса не показывает 100 %, пока запись прогона не перешла в «готово».
FRACTION_CAP = 0.99
_MB = 1024 * 1024

StepState = Literal["done", "active", "pending"]


def plan_stages(*, convert: bool, merge: bool) -> tuple[str, ...]:
    """Этапы конкретного прогона: конвертация только у DWG, склейка только у комплекта."""
    wanted = {name for name, present in (("convert", convert), ("merge", merge)) if present}
    return tuple(s.id for s in STAGES if s.id not in OPTIONAL or s.id in wanted)


@dataclass(frozen=True, slots=True)
class Step:
    id: str
    title: str
    state: StepState
    ms: float | None = None


@dataclass(frozen=True, slots=True)
class ProgressView:
    """Ход прогона глазами интерфейса: доля сделанного, прошло, осталось."""

    stage: str | None
    title: str
    fraction: float
    elapsed_s: float
    eta_s: float | None
    steps: tuple[Step, ...]


def estimate(progress: RunProgress, now: datetime) -> ProgressView:
    """Оценить долю сделанного и остаток по весам этапов и уже прошедшему времени.

    Доля не убывает: внутри этапа она растёт по часам до `STAGE_CAP` его ширины, на границе
    этапа перескакивает к его концу. Затянувшийся этап удлиняет оценку прогона на своё
    превышение - остаток растёт, а не замирает на одном числе.
    """
    total_weight = sum(_weight(s) for s in progress.stages) or 1.0
    weights = {s: _weight(s) / total_weight for s in progress.stages}

    prior = max(MIN_PRIOR_S, SECONDS_PER_MB * progress.source_bytes / _MB) * total_weight
    done_weight = sum(weights.get(t.stage, 0.0) for t in progress.done)
    done_s = sum(t.ms for t in progress.done) / 1000
    # Полная длительность: остаток по априорной оценке, поправленный на то, во сколько раз
    # завершённые этапы оказались быстрее или медленнее ожидания. Поправка входит в силу
    # постепенно (степень - доля сделанного): один короткий этап ещё ничего не доказывает,
    # а после чтения чертежа скорость прогона известна почти целиком.
    speed = done_s / (prior * done_weight) if done_weight > 0 else 1.0
    total = done_s + prior * (1 - done_weight) * speed**done_weight

    stage = progress.stage
    stage_weight = weights.get(stage, 0.0) if stage else 0.0
    stage_elapsed = (now - progress.stage_started_at).total_seconds() if stage else 0.0
    expected = total * stage_weight
    within = min(stage_elapsed / expected, STAGE_CAP) if expected > 0 else 0.0
    fraction = min(done_weight + stage_weight * within, FRACTION_CAP)
    total += max(0.0, stage_elapsed - expected)

    elapsed = (now - progress.started_at).total_seconds()
    finished = {t.stage: t.ms for t in progress.done}
    steps = tuple(
        Step(
            id=s,
            title=_title(s),
            state="done" if s in finished else "active" if s == stage else "pending",
            ms=finished.get(s),
        )
        for s in progress.stages
    )
    return ProgressView(
        stage=stage,
        title=_title(stage) if stage else "Готовимся к расчёту",
        fraction=round(fraction, 3),
        elapsed_s=round(elapsed, 1),
        eta_s=round(max(total - elapsed, 0.0), 1) if stage else None,
        steps=steps,
    )


def _weight(stage: str) -> float:
    known = BY_ID.get(stage)
    return known.weight if known is not None else _UNKNOWN_WEIGHT


def _title(stage: str) -> str:
    """Название этапа; этап, которого нет в таблице, не роняет полосу хода, а называется кодом."""
    known = BY_ID.get(stage)
    return known.title if known is not None else stage


__all__ = ["STAGES", "ProgressView", "Stage", "Step", "estimate", "plan_stages"]
