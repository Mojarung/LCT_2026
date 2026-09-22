"""Результаты прогона и записи о запусках."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING

from green.domain.objects import ReadDiagnostics

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from pathlib import Path

    from green.application.basemap import Basemap
    from green.application.classification import LayerCoverage
    from green.application.editing import RunContext
    from green.application.params import PlanParams
    from green.domain.norms import RuleBook
    from green.domain.planting import Plan


@dataclass(frozen=True, slots=True)
class StageTiming:
    stage: str
    ms: float


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Отпечатки исходных сущностей (handle -> digest), снятые до записи результата."""

    digests: Mapping[str, str]
    unexportable: int = 0


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Сверка исходных сущностей до и после записи результата."""

    source_entities: int
    unchanged: int
    changed: tuple[str, ...]
    missing: tuple[str, ...]
    added_outside_result_layers: tuple[str, ...]
    # Сущности исходника, которые ezdxf не экспортирует (REGION без ACIS-данных из LibreDWG):
    # их нет и не может быть в результате, поэтому они не считаются потерянными.
    unexportable: int = 0

    @property
    def ok(self) -> bool:
        return not (self.changed or self.missing or self.added_outside_result_layers)


@dataclass(frozen=True, slots=True)
class RunReport:
    run_id: str
    source_name: str
    source_sha256: str
    dxf_version: str
    profile: str
    params: PlanParams
    rulebook: RuleBook
    layer_map_fingerprint: str
    coverage: tuple[LayerCoverage, ...]
    class_counts: Mapping[str, int]
    plan: Plan
    integrity: IntegrityReport
    timings: tuple[StageTiming, ...]
    output_dxf: Path
    converter: str | None
    warnings: tuple[str, ...] = field(default=())
    # Подоснова для карты в вебе. Может отсутствовать: прогон из CLI её не требует, а на
    # чертеже без классифицированных объектов рисовать нечего.
    basemap: Basemap | None = None
    # Состояние прогона для интерактивной правки. В артефакты не попадает: живёт в памяти
    # сервиса ровно столько, сколько его там держат.
    context: RunContext | None = None
    read_diagnostics: ReadDiagnostics = field(default_factory=ReadDiagnostics)

    def summary(self) -> dict[str, object]:
        return {
            "placements": len(self.plan.placements),
            "allowed": self.plan.allowed_count,
            "needs_approval": self.plan.approval_count,
            "rejections": len(self.plan.rejections),
            "integrity_ok": self.integrity.ok,
            "total_ms": round(sum(t.ms for t in self.timings), 1),
            "stats": dict(self.plan.stats),
            "warnings": list(self.warnings),
        }


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RunProgress:
    """Ход прогона: план этапов, текущий этап и длительности завершённых.

    Есть в записи только пока прогон идёт. Секундомер сценария объявляет и этапы, которых в
    плане нет (конвертация у DXF, склейка у одиночного чертежа): они пропускаются, чтобы в
    интерфейсе не мелькал шаг, которому нечего делать.
    """

    stages: tuple[str, ...]
    started_at: datetime
    stage_started_at: datetime
    stage: str | None = None
    done: tuple[StageTiming, ...] = ()
    # Размер исходника с комплектом: по нему считается априорная длительность прогона.
    source_bytes: int = 0

    def begin(self, stage: str, now: datetime) -> RunProgress:
        """Закрыть текущий этап и открыть следующий; чужой или тот же этап ничего не меняет."""
        if stage not in self.stages or stage == self.stage:
            return self
        done = self.done
        if self.stage is not None:
            ms = round((now - self.stage_started_at).total_seconds() * 1000, 1)
            done = (*done, StageTiming(self.stage, ms))
        return replace(self, stage=stage, stage_started_at=now, done=done)


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    state: RunState
    source_name: str
    profile: str
    overrides: Mapping[str, object]
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    summary: Mapping[str, object] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    progress: RunProgress | None = None
