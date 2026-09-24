"""Объекты подосновы после чтения чертежа и классификации слоёв."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from shapely.geometry.base import BaseGeometry

NO_XREF = "00000000"


class ObjectClass(StrEnum):
    """Класс объекта подосновы, от которого считаются нормативные отступы."""

    UTILITY_WATER = "utility.water"
    UTILITY_SEWER = "utility.sewer"
    UTILITY_STORM = "utility.storm"
    UTILITY_DRAIN = "utility.drain"
    UTILITY_HEAT = "utility.heat"
    UTILITY_GAS = "utility.gas"
    UTILITY_POWER = "utility.power_cable"
    UTILITY_TELECOM = "utility.telecom"
    UTILITY_UNKNOWN = "utility.unknown"
    UTILITY_ACCESS = "utility.access"
    POWER_LINE_OVERHEAD = "power_line_overhead"
    POLE = "pole"
    CURB = "curb"
    PAVEMENT_EDGE = "pavement_edge"
    FENCE = "fence"
    ROAD = "road"
    SIDEWALK = "sidewalk"
    TRAM = "tram"
    RAILWAY = "railway"
    BUILDING = "building"
    STRUCTURE = "structure"
    SLOPE = "slope"
    WORK_BOUNDARY = "work_boundary"
    EXISTING_TREE = "existing_tree"
    EXISTING_SHRUB = "existing_shrub"
    LAWN = "lawn"
    IGNORE = "ignore"
    UNKNOWN = "unknown"

    @property
    def is_utility(self) -> bool:
        return self.value.startswith("utility.") and self is not ObjectClass.UTILITY_ACCESS

    @property
    def is_barrier_relaxable(self) -> bool:
        """«Инженерные сети и бордюры улиц и дорог»: к ним прим. 5 табл. 9.1 разрешает посадку
        дерева ближе нормы при прикорневом барьере. Колодцы, здания, опоры и тротуары - нет."""
        return self.is_utility or self in {ObjectClass.CURB, ObjectClass.ROAD}

    @property
    def is_hard_surface(self) -> bool:
        """Покрытие, внутри которого посадочное место не рассматривается вовсе."""
        return self in {
            ObjectClass.ROAD,
            ObjectClass.TRAM,
            ObjectClass.RAILWAY,
            ObjectClass.BUILDING,
            ObjectClass.SIDEWALK,
        }

    @property
    def is_surface_barrier(self) -> bool:
        """Возможный разделитель областей; сам по себе не доказывает материал."""
        return self in {
            ObjectClass.CURB,
            ObjectClass.PAVEMENT_EDGE,
            ObjectClass.BUILDING,
            ObjectClass.FENCE,
            ObjectClass.LAWN,
            ObjectClass.ROAD,
            ObjectClass.SIDEWALK,
            ObjectClass.TRAM,
            ObjectClass.RAILWAY,
            ObjectClass.WORK_BOUNDARY,
        }


@dataclass(frozen=True, slots=True)
class SourceRef:
    """Однозначная ссылка на исходную сущность в дереве XREF.

    Handle уникален только внутри одного файла, поэтому ссылка составная:
    короткий хеш файла, хеш цепочки внешних ссылок и handle.
    """

    file_sha8: str
    xref_hash8: str
    handle: str

    def __str__(self) -> str:
        return f"{self.file_sha8}:{self.xref_hash8}:{self.handle}"


@dataclass(frozen=True, slots=True)
class ClassificationEvidence:
    """Provenance, not a calibrated probability of semantic correctness."""

    method: str
    matched_rules: tuple[int, ...] = ()
    chosen_rules: tuple[int, ...] = ()
    override_key: str | None = None


@dataclass(frozen=True, slots=True)
class Feature:
    """Геометрический объект подосновы с исходным слоем и присвоенным классом."""

    ref: SourceRef
    layer: str
    geometry: BaseGeometry
    block: str | None = None
    object_class: ObjectClass = ObjectClass.UNKNOWN
    diameter_m: float | None = None
    # Радиус исходной окружности в метрах. Кругом кроны проектировщик обозначает посадку:
    # по нему нормоконтроль отличает дерево от кустарника.
    circle_radius_m: float | None = None
    classification: ClassificationEvidence | None = None
    # XY approximation error in metres. None means no established bound;
    # input quality must reject it before a plan can be certified.
    geometry_error_m: float | None = 0.0
    circle_center_m: tuple[float, float] | None = None
    # Distinguish closed linework from explicit fills after semantic mapping.
    # None carries no evidence that a polygon is just a boundary.
    source_entity_type: str | None = None
    # Штрих условного знака: строка ref экземпляра SymbolInstance, которому принадлежит.
    symbol: str | None = None


@dataclass(frozen=True, slots=True)
class TextLabel:
    """Текстовая подпись чертежа: источник диаметров сетей и других атрибутов."""

    ref: SourceRef
    layer: str
    x: float
    y: float
    text: str
    block: str | None = None
    # Only surface inference uses this role; utility diameter text is retained.
    surface_role: str = "auto"
    surface_evidence: ClassificationEvidence | None = None
    block_chain: tuple[str, ...] = ()
    # Подпись внутри условного знака: строка ref его экземпляра.
    symbol: str | None = None


@dataclass(frozen=True, slots=True)
class SymbolInstance:
    """Вставка условного знака: один объект подосновы в точке вставки (дерево, куст, люк).

    Примитивы знака остаются в сцене штрихами (Feature.symbol, TextLabel.symbol) со ссылкой
    на экземпляр. Контейнеры (обёртки MicroStation, DIMTXT, анонимные и крупные блоки) не
    знаки: знаком становится то, что внутри них.
    """

    ref: SourceRef
    block: str
    layer: str
    x: float
    y: float
    rotation_deg: float = 0.0
    scale: float = 1.0
    # Сколько примитивов знака прочитано в штрихи и подписи.
    strokes: int = 0


@dataclass(frozen=True, slots=True)
class GeometryGap:
    """Aggregated import loss with bounded examples for actionable diagnosis."""

    entity_type: str
    layer: str
    block: str | None
    reason: str
    count: int
    source_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReadDiagnostics:
    """Counts refer to visited modelspace entities and expanded block children.

    They are an import account, not a semantic recognition accuracy score. Paperspace
    is not part of the computational scene. Benign annotation skips are distinguished
    from missing block contents, which make spatial checks incomplete.
    """

    visited_by_type: Mapping[str, int] = field(default_factory=dict)
    skipped_by_type: Mapping[str, int] = field(default_factory=dict)
    unresolved_xrefs: tuple[str, ...] = ()
    geometry_gaps: tuple[GeometryGap, ...] = ()
    approximation_features: int = 0
    max_approximation_error_m: float = 0.0
    # Учёт чтения: у каждого посещённого примитива ровно один исход («feature», «label»,
    # «insert:symbol», «skipped:<ТИП>:<причина>» ...), сумма равна сумме visited_by_type.
    outcomes: Mapping[str, int] = field(default_factory=dict)

    @property
    def block_failures(self) -> tuple[str, ...]:
        return tuple(
            kind for kind in self.skipped_by_type if kind.startswith(("INSERT:", "VIRTUAL:"))
        )


@dataclass(frozen=True, slots=True)
class Scene:
    """Прочитанная подоснова: все объекты в единых координатах, в метрах.

    unit_m - сколько метров в единице чертежа. Сцена уже пересчитана, число нужно, чтобы
    записать результат обратно в единицах чертежа.
    """

    source_name: str
    source_sha256: str
    dxf_version: str
    features: tuple[Feature, ...]
    labels: tuple[TextLabel, ...] = field(default=())
    warnings: tuple[str, ...] = field(default=())
    unit_m: float = 1.0
    read_diagnostics: ReadDiagnostics = field(default_factory=ReadDiagnostics)
    symbols: tuple[SymbolInstance, ...] = field(default=())
