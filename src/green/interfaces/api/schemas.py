"""Схемы HTTP API. Стабильный контракт для будущего фронтенда."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from green.application.results import RunRecord, RunState


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
