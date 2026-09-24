"""Схемы конфигурационных файлов: валидация на границе, внутрь идут доменные объекты."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from green.application.classification import GeometryKind, MatchTarget
from green.application.params import DEFAULT_QUALITY_WEIGHTS, DEFAULT_WEIGHTS
from green.application.symbols import SymbolRole
from green.domain.norms import (
    CitationStatus,
    MeasureTo,
    PlantingType,
    RestrictionKind,
    Severity,
    Territory,
    genus_of,
)
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
    min_crown_m: float | None = Field(default=None, gt=0, le=40)
    traits: list[Literal["thorny", "toxic"]] = Field(default_factory=list)
    citation: CitationModel


_RULE_ID = r"^R-[A-Z0-9]+-[A-Z]+-\d{3}$"
_INVASIVE_GROUPS = 4  # 369-ПП, приложение 2: четыре группы


class InvasiveSpeciesModel(_Strict):
    rule_id: str = Field(pattern=_RULE_ID)
    species_lat: str = Field(min_length=3)
    group: int = Field(ge=1, le=_INVASIVE_GROUPS)
    citation: CitationModel


class InvasiveGroupModel(_Strict):
    rule_id: str = Field(pattern=_RULE_ID)
    group: int = Field(ge=1, le=_INVASIVE_GROUPS)
    conditional_on: list[Territory] = Field(default_factory=list)
    condition: str = ""
    citation: CitationModel

    @model_validator(mode="after")
    def _condition_named(self) -> InvasiveGroupModel:
        if self.conditional_on and not self.condition:
            raise ValueError(f"{self.rule_id}: для conditional_on нужен текст условия")
        return self


class SpeciesRestrictionModel(_Strict):
    rule_id: str = Field(pattern=_RULE_ID)
    kind: RestrictionKind
    citation: CitationModel


class RulesFile(_Strict):
    version: int = 1
    distance_rules: list[DistanceRuleModel]
    invasive_species: list[InvasiveSpeciesModel] = Field(default_factory=list)
    invasive_groups: list[InvasiveGroupModel] = Field(default_factory=list)
    species_restrictions: list[SpeciesRestrictionModel] = Field(default_factory=list)

    @model_validator(mode="after")
    def _every_listed_group_has_a_rule(self) -> RulesFile:
        ruled = {g.group for g in self.invasive_groups}
        missing = sorted({s.group for s in self.invasive_species} - ruled)
        if missing:
            raise ValueError(f"нет порядка 369-ПП для групп: {missing}")
        return self


class LayerRuleModel(_Strict):
    pattern: str
    target: MatchTarget = MatchTarget.LAYER
    geometry: GeometryKind = GeometryKind.ANY
    object_class: ObjectClass
    confirmed: bool = False
    note: str = ""
    priority: int = 0

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, value: str) -> str:
        re.compile(value)
        return value


class LayerMapFile(_Strict):
    version: int = 1
    rules: list[LayerRuleModel]


class SymbolModel(_Strict):
    object_class: ObjectClass = Field(alias="class")
    role: SymbolRole
    confirmed: bool = False
    note: str = ""
    source: str = ""


class SymbolsFile(_Strict):
    """config/symbols.yaml: код условного знака -> класс объекта и роль знака."""

    version: int = 1
    symbols: dict[str, SymbolModel]


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
    planting_sex: Literal["male"] | None = None
    fruit_litter: bool = False
    invasive_group: int | None = Field(default=None, ge=1, le=_INVASIVE_GROUPS)
    decor_months: list[int] = Field(default_factory=list)
    uses: list[Literal["row", "group", "solitaire", "hedge", "under_lines", "grate"]] = Field(
        default_factory=list
    )
    care_level: int = Field(default=1, ge=1, le=3)
    pilot_streets: int = Field(default=0, ge=0)
    pilot_count: int = Field(default=0, ge=0)
    categories: dict[
        Literal["parks", "squares", "streets", "yards", "special"],
        Literal["plus", "limited", "minus"],
    ] = Field(default_factory=dict)
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
        # Признаки, по которым вид запрещается нормой, без источника превращаются в
        # запрет «потому что так записано в каталоге».
        restricting = {
            "allergen": self.allergen >= _MASS_ALLERGEN,
            "fluff": self.fluff,
            "fruit_litter": self.fruit_litter,
            "planting_sex": self.planting_sex is not None,
            "categories": bool(self.categories),
        }
        unsourced = sorted(k for k, on in restricting.items() if on and k not in self.sources)
        if unsourced:
            raise ValueError(f"{self.code}: нет источника в sources для {', '.join(unsourced)}")
        return self


_MASS_ALLERGEN = 2


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
    require_known_objects: bool = True
    semantic_source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    layer_classes: dict[str, ObjectClass] = Field(default_factory=dict)
    block_classes: dict[str, ObjectClass] = Field(default_factory=dict)
    feature_classes: dict[str, ObjectClass] = Field(default_factory=dict)
    label_roles: dict[str, Literal["soil", "paved", "ignore"]] = Field(default_factory=dict)
    allow_needs_approval: bool = True
    label_search_radius_m: float = Field(default=3.0, gt=0, le=20)
    max_rejections: int = Field(default=2000, ge=0, le=100_000)
    require_soil: bool = True
    require_work_boundary: bool = True
    planting_radius_m: float = Field(default=1.6, ge=0, le=10)
    shrub_planting_radius_m: float = Field(default=0.5, ge=0, le=10)
    surface_cell_m: float = Field(default=0.5, ge=0.1, le=5.0)
    surface_inference_mode: Literal["closed_faces", "distance"] = "closed_faces"
    surface_max_distance_m: float = Field(default=30.0, gt=0, le=500)
    surface_ambiguity_m: float = Field(default=1.0, ge=0, le=20)
    tree_seed_distance_m: float = Field(default=2.0, ge=0, le=20)
    drawing_unit: Literal["auto", "m", "dm", "cm", "mm", "km", "in", "ft", "yd"] = "auto"
    modes: tuple[Literal["alley", "lawn"], ...] = Field(default=("alley", "lawn"), min_length=1)
    placement_solver: Literal["greedy", "milp", "portfolio"] = "portfolio"
    placement_time_limit_s: float = Field(default=5.0, gt=0, le=60)
    placement_max_candidates: int = Field(default=6000, ge=1, le=50_000)
    placement_max_conflicts: int = Field(default=200_000, ge=1, le=2_000_000)
    lawn_phase: tuple[Annotated[float, Field(ge=0, lt=1)], Annotated[float, Field(ge=0, lt=1)]] = (
        0.0,
        0.0,
    )
    lawn_rotation_deg: float = Field(default=0.0, ge=-180, le=180)
    lawn_anchor: Literal["raster", "soil"] = "raster"
    zones: bool = True
    zone_cell_m: float = Field(default=1.0, ge=0.25, le=10.0)
    assortment_mode: Literal["auto", "given", "single"] = "auto"
    assortment_solver: Literal["auto", "greedy"] = "auto"
    given_assortment: dict[str, int] = Field(default_factory=dict)
    region_hardiness_zone: int = Field(default=4, ge=1, le=9)
    salt_zone_m: float = Field(default=5.0, ge=0, le=100)
    max_height_under_lines_m: float = Field(default=4.0, gt=0, le=50)
    crown_extra_per_m: float = Field(default=0.5, ge=0, le=5)
    crown_extra_classes: tuple[ObjectClass, ...] = ()
    territory: Territory = Territory.GREEN_FUND
    planting_category: Literal["parks", "squares", "streets", "yards", "special"] = "streets"
    disabled_rules: tuple[str, ...] = ()
    root_barriers: bool = False
    shrub_groups: bool = True
    shrub_group_spacing_m: float = Field(default=1.0, ge=0.3, le=3.0)
    shrub_group_size: int = Field(default=3, ge=1, le=5)
    shrub_quota_species: float = Field(default=0.20, gt=0, le=1)
    shrub_quota_genus: float = Field(default=0.35, gt=0, le=1)
    shrub_quota_family: float = Field(default=0.50, gt=0, le=1)
    shrub_conifer_share: tuple[float, float] = Field(default=(0.0, 0.30))
    shrub_quotas_use_inventory: bool = False
    quota_species: float = Field(default=0.10, gt=0, le=1)
    quota_genus: float = Field(default=0.20, gt=0, le=1)
    quota_family: float = Field(default=0.30, gt=0, le=1)
    conifer_share: tuple[float, float] = Field(default=(0.15, 0.40))
    structure_patch_size: int = Field(default=10, ge=1, le=200)
    assortment_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    quality_weights: dict[str, float] = Field(default_factory=dict)
    density_trees_per_km: tuple[float, float] = Field(default=(150.0, 180.0))
    density_shrubs_per_km: tuple[float, float] = Field(default=(600.0, 720.0))
    row_spacing_m: tuple[float, float] = Field(default=(5.0, 6.0))
    canopy_target: float = Field(default=1.0, gt=0, le=5)
    dust_target: float = Field(default=0.50, gt=0, le=1)
    margin_target: float = Field(default=0.20, gt=0, le=5)
    diversity_target: int = Field(default=10, ge=1, le=100)

    @field_validator("density_trees_per_km", "density_shrubs_per_km", "row_spacing_m")
    @classmethod
    def _fork(cls, value: tuple[float, float]) -> tuple[float, float]:
        low, high = value
        if not 0 < low <= high:
            raise ValueError("вилка задаётся парой 0 < от <= до")
        return value

    @field_validator("quality_weights")
    @classmethod
    def _quality_weights(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(value) - set(DEFAULT_QUALITY_WEIGHTS))
        if unknown:
            raise ValueError(f"quality_weights: неизвестные слагаемые {', '.join(unknown)}")
        if any(weight < 0 for weight in value.values()):
            raise ValueError("quality_weights: вес не может быть отрицательным")
        return value

    @field_validator("disabled_rules")
    @classmethod
    def _rule_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        bad = [rule_id for rule_id in value if not re.fullmatch(_RULE_ID, rule_id)]
        if bad:
            raise ValueError(f"disabled_rules: некорректные rule_id {bad}")
        return tuple(sorted(set(value)))

    @field_validator("conifer_share", "shrub_conifer_share")
    @classmethod
    def _share(cls, value: tuple[float, float]) -> tuple[float, float]:
        low, high = value
        if not 0 <= low <= high <= 1:
            raise ValueError("conifer_share: доля хвойных задаётся парой 0 <= min <= max <= 1")
        return value

    @field_validator("assortment_weights")
    @classmethod
    def _weights(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(value) - set(DEFAULT_WEIGHTS))
        if unknown:
            raise ValueError(f"assortment_weights: неизвестные факторы {', '.join(unknown)}")
        if any(weight < 0 for weight in value.values()):
            raise ValueError("assortment_weights: вес не может быть отрицательным")
        if value and sum(value.values()) <= 0:
            raise ValueError("assortment_weights: сумма весов должна быть больше нуля")
        return value
