"""План посадок: принятые посадки, отказы и трасса проверенных правил."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from shapely.geometry.base import BaseGeometry

    from green.domain.norms import PlantingType
    from green.domain.objects import ObjectClass, SourceRef


class Verdict(StrEnum):
    ALLOWED = "allowed"
    FORBIDDEN = "forbidden"
    NEEDS_APPROVAL = "needs_approval"
    UNKNOWN = "unknown"


class CheckOutcome(StrEnum):
    PASS = "pass"  # noqa: S105 - исход проверки, не пароль
    FAIL = "fail"
    NO_DATA = "no_data"


class LifeForm(StrEnum):
    """Жизненная форма: определяет, куда вид вообще может быть назначен."""

    TREE_LARGE = "tree_large"  # взрослая высота 20 м и выше
    TREE_MEDIUM = "tree_medium"  # 10-20 м
    TREE_SMALL = "tree_small"  # до 10 м
    SHRUB_TALL = "shrub_tall"  # выше 2 м
    SHRUB_MEDIUM = "shrub_medium"  # 1-2 м
    SHRUB_LOW = "shrub_low"  # ниже 1 м
    GROUNDCOVER = "groundcover"
    PERENNIAL = "perennial"


TREE_FORMS = frozenset({LifeForm.TREE_LARGE, LifeForm.TREE_MEDIUM, LifeForm.TREE_SMALL})
SHRUB_FORMS = frozenset({LifeForm.SHRUB_TALL, LifeForm.SHRUB_MEDIUM, LifeForm.SHRUB_LOW})
CONIFER_FAMILIES = frozenset({"Pinaceae", "Cupressaceae", "Taxaceae"})


@dataclass(frozen=True, slots=True)
class Species:
    """Вид или сорт из ассортимента.

    Первые четыре поля — то, без чего нельзя нарисовать посадку; остальные описывают
    пригодность вида к месту и его ограничения, у каждого поля свой источник в sources
    (имя поля -> откуда значение) и общий status: verified - сверено с актом, reference -
    из справочника, pilot - из паспортов пилотных улиц, draft - требует проверки.
    Эвристику нельзя выдавать за норму: статус и источник попадают в объяснение посадки.
    """

    code: str
    name_ru: str
    name_lat: str
    crown_diameter_m: float  # крона через 10 лет, для отрисовки условного знака
    genus: str = ""  # латинский род в нижнем регистре, как genus_of()
    family: str = ""
    life_form: LifeForm = LifeForm.TREE_MEDIUM
    height_m: float = 0.0  # взрослая высота
    crown_mature_m: float = 0.0  # диаметр взрослой кроны, для прим. к табл. 9.1 СП 42.13330
    evergreen: bool = False
    root_type: str = "mixed"  # surface | tap | mixed
    growth: str = "medium"  # slow | medium | fast
    lifespan_years: int = 0
    hardiness_zone: int = 4  # USDA, минимальная зона, которую вид переносит
    light: str = "sun"  # минимальная потребность: shade | semi | sun
    moisture: str = "mesic"  # dry | mesic | wet | any
    salt_tolerance: int = 1  # 0 - не переносит реагенты, 2 - устойчив
    gas_tolerance: int = 1
    compaction_tolerance: int = 1
    # 0 - нет, 1 - слабый, 2 - вызывает массовые аллергические реакции (743-ПП п. 3.6.18)
    allergen: int = 0
    toxic: bool = False
    thorny: bool = False
    fluff: bool = False  # женские экземпляры дают пух (743-ПП п. 3.6.18)
    planting_sex: str | None = None  # male - в посадку идут только мужские клоны
    fruit_litter: bool = False  # засоряет территорию во время плодоношения (743-ПП п. 3.6.18)
    invasive_group: int | None = None  # группа по перечню 369-ПП (приложение 1)
    decor_months: frozenset[int] = frozenset()  # месяцы пиковой декоративности
    uses: frozenset[str] = frozenset()  # row | group | solitaire | hedge | under_lines | grate
    care_level: int = 1  # 1 - минимальный уход, 3 - требовательный
    pilot_streets: int = 0  # в скольких паспортах пилотных улиц встречается
    pilot_count: int = 0
    status: str = "draft"
    sources: Mapping[str, str] = field(default_factory=dict, compare=False)

    @property
    def is_conifer(self) -> bool:
        return self.family in CONIFER_FAMILIES

    @property
    def is_tree(self) -> bool:
        return self.life_form in TREE_FORMS

    @property
    def is_shrub(self) -> bool:
        return self.life_form in SHRUB_FORMS


@dataclass(frozen=True, slots=True)
class Reason:
    """Основание решения о виде: норма, справочник, эмпирика пилота или параметр участка.

    kind различает их намеренно: рекомендация справочника, поданная как норма, - ложная
    ссылка на акт. rule_id заполняется только у norm, source несёт цитату или справочник.
    """

    kind: str  # norm | reference | pilot | composition | parameter
    text: str
    rule_id: str = ""
    source: str = ""
    # Условие, при котором акт допускает посадку (мужские клоны тополя, контроль
    # распространения вида группы III): попадает в предупреждения плана как обязательство.
    condition: str = ""


@dataclass(frozen=True, slots=True)
class Alternative:
    """Вид, который подошёл бы этой точке, но уступил выбранному."""

    code: str
    name_ru: str
    percent: int
    why_not: str


@dataclass(frozen=True, slots=True)
class AssortmentInfo:
    """Почему в этой точке именно этот вид: оценка, структура, основания и альтернативы."""

    status: str  # assigned | given | single | no_species
    percent: int
    factors: Mapping[str, float]
    structure_id: str | None = None
    structure_kind: str | None = None
    reasons: tuple[Reason, ...] = field(default=())
    alternatives: tuple[Alternative, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class AssortmentSummary:
    """Состав плана: доли, разнообразие, сезонность и то, чего сделать не удалось."""

    mode: str
    solver: str
    counts: Mapping[str, int]
    genus_shares: Mapping[str, float]
    family_shares: Mapping[str, float]
    conifer_share: float
    shannon: float
    decor_by_month: Mapping[int, int]
    no_species: int
    quota_violations: tuple[str, ...] = field(default=())
    existing: Mapping[str, int] = field(default_factory=dict)
    # Сколько пар «посадка - вид» отсеяно и по какому основанию: без этих чисел отчёт
    # показывает только то, что осталось, и молчаливый отсев неотличим от успеха.
    rejected_by_kind: Mapping[str, int] = field(default_factory=dict)
    rejected_by_rule: Mapping[str, int] = field(default_factory=dict)
    notes: tuple[str, ...] = field(default=())


@dataclass(frozen=True, slots=True)
class RuleCheck:
    """Результат проверки одного правила для одной точки."""

    rule_id: str
    outcome: CheckOutcome
    threshold_m: float | None = None
    measured_m: float | None = None
    nearest: SourceRef | None = None
    object_class: ObjectClass | None = None


@dataclass(frozen=True, slots=True)
class Placement:
    placement_id: str
    number: int
    planting_type: PlantingType
    species: Species
    x: float
    y: float
    verdict: Verdict
    checks: tuple[RuleCheck, ...]
    notes: tuple[str, ...] = field(default=())
    assortment: AssortmentInfo | None = None


@dataclass(frozen=True, slots=True)
class Rejection:
    rejection_id: str
    number: int
    planting_type: PlantingType
    x: float
    y: float
    verdict: Verdict
    blocking: tuple[RuleCheck, ...]
    # Место допустимо по нормам, но не занято: причина не из правил расстояний (квоты
    # разнообразия, заданные количества). У отказа по нормам поле пустое.
    note: str = ""


@dataclass(frozen=True, slots=True)
class Explanation:
    """Человекочитаемое объяснение решения, собранное только из трассы правил."""

    subject_id: str
    number: int
    kind: str
    text: str


@dataclass(frozen=True, slots=True)
class Zone:
    """Зона допустимости: где посадка данного типа получает данный вердикт по всем правилам."""

    verdict: Verdict
    geometry: BaseGeometry

    @property
    def area_m2(self) -> float:
        return float(self.geometry.area)


@dataclass(frozen=True, slots=True)
class Plan:
    placements: tuple[Placement, ...]
    rejections: tuple[Rejection, ...]
    explanations: tuple[Explanation, ...] = field(default=())
    warnings: tuple[str, ...] = field(default=())
    stats: Mapping[str, int | float] = field(default_factory=dict)
    zones: tuple[Zone, ...] = field(default=())
    assortment_summary: AssortmentSummary | None = None

    @property
    def allowed_count(self) -> int:
        return sum(1 for p in self.placements if p.verdict is Verdict.ALLOWED)

    @property
    def approval_count(self) -> int:
        return sum(1 for p in self.placements if p.verdict is Verdict.NEEDS_APPROVAL)
