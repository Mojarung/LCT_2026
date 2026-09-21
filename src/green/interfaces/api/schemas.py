"""Схемы HTTP API. Стабильный контракт для будущего фронтенда."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from green.application.results import RunRecord, RunState
from green.domain.planting import Plan, RuleCheck


class HealthOut(BaseModel):
    status: Literal["ok"] = "ok"
    version: str


class SpeciesOut(BaseModel):
    code: str
    name_ru: str
    name_lat: str
    crown_diameter_m: float


class ConverterOut(BaseModel):
    name: str
    available: bool


class RulesOut(BaseModel):
    total: int
    verified: int
    fingerprint: str


class MetaOut(BaseModel):
    version: str
    default_profile: str
    profiles: list[str]
    result_layers: list[str]
    rules: RulesOut
    species: list[SpeciesOut]
    converters: list[ConverterOut]


class ArtifactOut(BaseModel):
    name: str
    url: str


class RunOut(BaseModel):
    id: str
    state: RunState
    source_name: str
    profile: str
    overrides: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    error: str | None = None
    summary: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactOut] = Field(default_factory=list)

    @classmethod
    def from_record(cls, record: RunRecord, artifact_url: Callable[[str, str], str]) -> RunOut:
        return cls(
            id=record.run_id,
            state=record.state,
            source_name=record.source_name,
            profile=record.profile,
            overrides=dict(record.overrides),
            created_at=record.created_at,
            updated_at=record.updated_at,
            error=record.error,
            summary=dict(record.summary),
            artifacts=[
                ArtifactOut(name=name, url=artifact_url(record.run_id, name))
                for name in record.artifacts
            ],
        )


class RunListOut(BaseModel):
    items: list[RunOut]


class RuleCheckOut(BaseModel):
    rule_id: str
    outcome: str
    threshold_m: float | None = None
    measured_m: float | None = None
    object_class: str | None = None

    @classmethod
    def from_check(cls, check: RuleCheck) -> RuleCheckOut:
        return cls(
            rule_id=check.rule_id,
            outcome=check.outcome.value,
            threshold_m=check.threshold_m,
            measured_m=check.measured_m,
            object_class=check.object_class.value if check.object_class else None,
        )


class CheckIn(BaseModel):
    """Точка в координатах чертежа. Вид задаёт состав правил: нормы зависят от породы."""

    x: float
    y: float
    species: str | None = None


class CheckOut(BaseModel):
    verdict: str
    plantable: bool
    needs_barrier: bool
    note: str = ""
    checks: list[RuleCheckOut] = Field(default_factory=list)


class EditIn(BaseModel):
    kind: Literal["move", "delete", "add"]
    placement_id: str | None = None
    x: float | None = None
    y: float | None = None
    species: str | None = None


class EditsIn(BaseModel):
    edits: list[EditIn] = Field(min_length=1, max_length=500)


class PlanSummaryOut(BaseModel):
    """Состояние плана после правки.

    stale означает, что файлы результата уже не соответствуют плану на экране: правки
    приняты, но DXF и объяснения пересобираются отдельной командой.
    """

    placements: int
    allowed: int
    needs_approval: int
    rejections: int
    stale: bool

    @classmethod
    def from_plan(cls, plan: Plan, *, stale: bool) -> PlanSummaryOut:
        return cls(
            placements=len(plan.placements),
            allowed=plan.allowed_count,
            needs_approval=plan.approval_count,
            rejections=len(plan.rejections),
            stale=stale,
        )
