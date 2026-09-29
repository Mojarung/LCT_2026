"""Схемы HTTP API. Стабильный контракт для будущего фронтенда."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from green.application.progress import ProgressView, estimate
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


class StreetOut(BaseModel):
    """Улица пилотного проекта, подготовленная в каталоге на диске."""

    slug: str
    number: int
    title: str
    files: int
    size_mb: float


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


class ProfileOut(BaseModel):
    """Параметры профиля, которые показывает форма запуска.

    Форма заполняется ими и отправляет в overrides только изменённое человеком: иначе выбор
    профиля терялся под значениями формы по умолчанию.
    """

    name: str
    planting_type: str = Field(description="tree или shrub")
    spacing_m: float = Field(description="Шаг посадки, м")
    modes: list[str] = Field(description="Приёмы размещения: alley, lawn, fill")
    root_barriers: bool
    shrub_groups: bool
    shrub_rows: bool
    curb_hedges: bool
    understory: bool
    shrub_fill: bool = Field(description="Группы кустарника на свободном газоне")
    lawns: bool = Field(description="Газоны на грунте, который посадки оставили свободным")


class ArtifactOut(BaseModel):
    name: str
    url: str
    size_bytes: int | None = Field(default=None, description="Размер файла; null, если его нет")


class StepOut(BaseModel):
    id: str
    title: str
    state: Literal["done", "active", "pending"]
    ms: float | None = Field(default=None, description="Длительность завершённого этапа")


class ProgressOut(BaseModel):
    """Ход прогона: есть только пока он идёт.

    Доля и остаток - оценка по весам этапов и прошедшему времени; подоснова для карты
    (`basemap.geojson`) появляется в `artifacts` раньше остальных файлов.
    """

    stage: str | None = Field(description="Текущий этап или null до первого этапа")
    title: str = Field(description="Название этапа для человека")
    fraction: float = Field(ge=0, le=1, description="Доля сделанного, 0..1")
    elapsed_s: float = Field(description="Секунд с начала расчёта")
    eta_s: float | None = Field(description="Оценка остатка в секундах")
    steps: list[StepOut]

    @classmethod
    def from_view(cls, view: ProgressView) -> ProgressOut:
        return cls(
            stage=view.stage,
            title=view.title,
            fraction=view.fraction,
            elapsed_s=view.elapsed_s,
            eta_s=view.eta_s,
            steps=[StepOut(id=s.id, title=s.title, state=s.state, ms=s.ms) for s in view.steps],
        )


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
    progress: ProgressOut | None = Field(
        default=None, description="Ход расчёта; null, пока прогон в очереди или уже закончен"
    )

    @classmethod
    def from_record(
        cls,
        record: RunRecord,
        artifact_url: Callable[[str, str], str],
        artifact_size: Callable[[str, str], int | None] | None = None,
    ) -> RunOut:
        size = artifact_size or (lambda _run_id, _name: None)
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
                ArtifactOut(
                    name=name,
                    url=artifact_url(record.run_id, name),
                    size_bytes=size(record.run_id, name),
                )
                for name in record.artifacts
            ],
            progress=(
                ProgressOut.from_view(estimate(record.progress, datetime.now(UTC)))
                if record.progress is not None
                else None
            ),
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
    """Итог проверки точки: по нормам (verdict) и по месту (plantable) - это разные вопросы."""

    verdict: str = Field(
        description=(
            "Итог по нормам: allowed - посадка допустима, needs_approval - допустима при"
            " согласовании, forbidden - запрещена (ближе нормы к объекту, место непригодно"
            " или вид здесь запрещён)"
        )
    )
    plantable: bool = Field(
        description=(
            "Посадочное место целиком на пригодном грунте внутри границы работ и не задевает"
            " препятствий, без учёта отступов от сетей и сооружений. Поэтому verdict"
            " forbidden при plantable true - точка на грунте, но ближе нормы к объекту"
        )
    )
    needs_barrier: bool = Field(
        description="Место допустимо только с корнезащитным (прикорневым) барьером"
    )
    note: str = Field(
        default="",
        description=(
            "Причина по-русски, если место непригодно или вид здесь запрещён; нарушения"
            " отступов - в checks"
        ),
    )
    checks: list[RuleCheckOut] = Field(
        default_factory=list,
        description="Проверка каждого правила отступа: норма, замер, итог",
    )


class EditIn(BaseModel):
    kind: Literal["move", "delete", "add"]
    placement_id: str | None = None
    x: float | None = None
    y: float | None = None
    species: str | None = None


class EditsIn(BaseModel):
    edits: list[EditIn] = Field(min_length=1, max_length=500)


class DraftOut(BaseModel):
    """Current in-memory draft; artifacts remain the last successful export."""

    plan: dict[str, Any]
    quality: dict[str, Any]
    stale: bool


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
