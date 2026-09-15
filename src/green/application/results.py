"""Результаты прогона и записи о запусках."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping
    from datetime import datetime
    from pathlib import Path

    from green.application.classification import LayerCoverage
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


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    """Сверка исходных сущностей до и после записи результата."""

    source_entities: int
    unchanged: int
    changed: tuple[str, ...]
    missing: tuple[str, ...]
    added_outside_result_layers: tuple[str, ...]

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

    def summary(self) -> dict[str, object]:
        return {
            "placements": len(self.plan.placements),
            "allowed": self.plan.allowed_count,
            "needs_approval": self.plan.approval_count,
            "rejections": len(self.plan.rejections),
            "integrity_ok": self.integrity.ok,
            "total_ms": round(sum(t.ms for t in self.timings), 1),
            "warnings": list(self.warnings),
        }


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


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
