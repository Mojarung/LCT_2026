"""Схемы конфигурационных файлов: валидация на границе, внутрь идут доменные объекты."""

from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from green.application.classification import MatchTarget
from green.domain.norms import CitationStatus, MeasureTo, PlantingType, Severity
from green.domain.objects import ObjectClass


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ActModel(_Strict):
    act_id: str = Field(pattern=r"^[A-Z0-9_]+$")
    title: str
    edition: str
    url: str
    checked_at: date | None = None


class ActsFile(_Strict):
    version: int = 1
    acts: list[ActModel]


class CitationModel(_Strict):
    act_id: str
    clause: str
    quote: str = ""
    status: CitationStatus = CitationStatus.UNVERIFIED


class DistanceRuleModel(_Strict):
    rule_id: str = Field(pattern=r"^R-[A-Z0-9]+-[A-Z]+-\d{3}$")
    object_class: ObjectClass
    planting_type: PlantingType
    min_distance_m: float = Field(ge=0, le=100)
    measure_to: MeasureTo = MeasureTo.UNSPECIFIED
    severity: Severity = Severity.FORBID
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
    code: str = Field(pattern=r"^[a-z0-9_]+$")
    name_ru: str
    name_lat: str
    crown_diameter_m: float = Field(gt=0, le=30)


class SpeciesFile(_Strict):
    version: int = 1
    species: list[SpeciesModel]


class ProfileModel(_Strict):
    description: str = ""
    planting_type: PlantingType = PlantingType.TREE
    species_code: str = "tilia_cordata"
    spacing_m: float = Field(default=8.0, gt=1, le=50)
    curb_offsets_m: tuple[float, ...] = Field(default=(2.0, 2.5, 3.0), min_length=1, max_length=10)
    require_utility_data: bool = True
    unknown_lines_as_utility: bool = True
    allow_needs_approval: bool = True
    label_search_radius_m: float = Field(default=3.0, gt=0, le=20)
    max_rejections: int = Field(default=2000, ge=0, le=100_000)
    require_soil: bool = True
    surface_cell_m: float = Field(default=0.5, ge=0.1, le=5.0)
