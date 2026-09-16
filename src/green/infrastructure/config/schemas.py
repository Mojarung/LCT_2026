"""Схемы конфигурационных файлов: валидация на границе, внутрь идут доменные объекты."""

from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from green.application.classification import GeometryKind, MatchTarget
from green.domain.norms import CitationStatus, MeasureTo, PlantingType, Severity, genus_of
from green.domain.objects import ObjectClass
from green.domain.planting import LifeForm


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActModel(_Strict):
    act_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    short: str = ""
    title: str
    edition: str
    url: str
    checked_at: date | None = None


class ActsFile(_Strict):
    version: int = 1
    acts: list[ActModel]


class ReferenceModel(_Strict):
    act_id: str
    clause: str


class CitationModel(_Strict):
    act_id: str
    clause: str
    quote: str = ""
    status: CitationStatus = CitationStatus.UNVERIFIED
    related: list[ReferenceModel] = Field(default_factory=list)


class DistanceRuleModel(_Strict):
    rule_id: str = Field(pattern=r"^R-[A-Z0-9]+-[A-Z]+-\d{3}$")
    object_class: ObjectClass
    planting_type: PlantingType
    min_distance_m: float = Field(ge=0, le=100)
    measure_to: MeasureTo = MeasureTo.UNSPECIFIED
    severity: Severity = Severity.FORBID
    genera: list[str] = Field(default_factory=list)
    citation: CitationModel


class SpeciesBanModel(_Strict):
    rule_id: str = Field(pattern=r"^R-[A-Z0-9]+-[A-Z]+-\d{3}$")
    species_lat: str
    citation: CitationModel


class RulesFile(_Strict):
    version: int = 1
    distance_rules: list[DistanceRuleModel]
    species_bans: list[SpeciesBanModel] = Field(default_factory=list)


class LayerRuleModel(_Strict):
    pattern: str
    target: MatchTarget = MatchTarget.LAYER
    geometry: GeometryKind = GeometryKind.ANY
    object_class: ObjectClass
    confirmed: bool = False
    note: str = ""

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        re.compile(value)
        return value


class LayerMapFile(_Strict):
    version: int = 1
    rules: list[LayerRuleModel]


class SpeciesModel(_Strict):
    """Запись ассортимента. Обязательны поля, без которых подбор вида не работает."""

    code: str = Field(pattern=r"^[a-z0-9_]+$")
    name_ru: str
    name_lat: str
    crown_diameter_m: float = Field(gt=0, le=30)
    genus: str = Field(pattern=r"^[a-z]+$")
    family: str = Field(pattern=r"^[A-Z][a-z]+$")
    life_form: LifeForm
    height_m: float = Field(gt=0, le=100)
    crown_mature_m: float = Field(gt=0, le=40)
    hardiness_zone: int = Field(ge=1, le=9)
    salt_tolerance: int = Field(ge=0, le=2)
    sources: dict[str, str] = Field(min_length=1)
    evergreen: bool = False
    root_type: Literal["surface", "tap", "mixed"] = "mixed"
    growth: Literal["slow", "medium", "fast"] = "medium"
    lifespan_years: int = Field(default=0, ge=0, le=1000)
    light: Literal["shade", "semi", "sun"] = "sun"
    moisture: Literal["dry", "mesic", "wet", "any"] = "mesic"
    gas_tolerance: int = Field(default=1, ge=0, le=2)
    compaction_tolerance: int = Field(default=1, ge=0, le=2)
    allergen: int = Field(default=0, ge=0, le=2)
    toxic: bool = False
    thorny: bool = False
    fluff: bool = False
    fruit_litter: bool = False
    invasive_group: int | None = Field(default=None, ge=1, le=4)
    decor_months: list[int] = Field(default_factory=list)
    uses: list[Literal["row", "group", "solitaire", "hedge", "under_lines", "grate"]] = Field(
        default_factory=list
    )
    care_level: int = Field(default=1, ge=1, le=3)
    pilot_streets: int = Field(default=0, ge=0)
    pilot_count: int = Field(default=0, ge=0)
    status: Literal["verified", "reference", "pilot", "draft"] = "draft"

    @field_validator("decor_months")
    @classmethod
    def _months(cls, value: list[int]) -> list[int]:
        if any(m < 1 or m > 12 for m in value):  # noqa: PLR2004 - календарные месяцы
            raise ValueError("decor_months: месяцы задаются числами 1-12")
        return value

    @model_validator(mode="after")
    def _genus_matches_latin_name(self) -> SpeciesModel:
        expected = genus_of(self.name_lat)
        if self.genus != expected:
            raise ValueError(f"{self.code}: genus '{self.genus}' не равен роду из name_lat")
        if "hardiness_zone" not in self.sources or "salt_tolerance" not in self.sources:
            raise ValueError(
                f"{self.code}: sources должен называть hardiness_zone и salt_tolerance"
            )
        return self


class SpeciesFile(_Strict):
    version: Literal[2] = 2
    species: list[SpeciesModel]


class ProfileModel(_Strict):
    description: str = ""
    planting_type: PlantingType = PlantingType.TREE
    species_code: str = "tilia_cordata"
    spacing_m: float = Field(default=6.0, ge=0.3, le=50)
    curb_offsets_m: tuple[float, ...] = Field(default=(2.0, 2.5, 3.0), min_length=1, max_length=10)
    require_utility_data: bool = True
    unknown_lines_as_utility: bool = True
    allow_needs_approval: bool = True
    label_search_radius_m: float = Field(default=3.0, gt=0, le=20)
    max_rejections: int = Field(default=2000, ge=0, le=100_000)
    require_soil: bool = True
    surface_cell_m: float = Field(default=0.5, ge=0.1, le=5.0)
    modes: tuple[Literal["alley", "lawn"], ...] = Field(default=("alley", "lawn"), min_length=1)
    zones: bool = True
    zone_cell_m: float = Field(default=1.0, ge=0.25, le=10.0)
