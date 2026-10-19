"""Чтение DXF в доменную сцену: геометрия Shapely, исходный слой и ссылка на сущность."""

from __future__ import annotations

import hashlib
import struct
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from ezdxf import bbox
from ezdxf.entities import (
    Arc,
    Attrib,
    Body,
    Circle,
    Ellipse,
    Insert,
    Linetype,
    LWPolyline,
    MText,
    Polyline,
    Spline,
    Text,
)
from ezdxf.lldxf.encoding import decode_dxf_unicode
from ezdxf.path import make_path
from ezdxf.render import MeshBuilder
from ezdxf.tools.text import fast_plain_mtext, plain_text
from ezdxf.xclip import XClip
from shapely.geometry import LineString, Point, Polygon

from green.application.diameters import parse_diameter_m
from green.application.semantic_names import local_name
from green.domain.objects import (
    NO_XREF,
    Feature,
    GeometryGap,
    ReadDiagnostics,
    Scene,
    SourceRef,
    SymbolInstance,
    TextLabel,
)
from green.infrastructure.cad.acis_region import RegionGeometryError, region_polygon
from green.infrastructure.cad.curve_paths import (
    circle_vertices,
    ellipse_vertices,
    fitted_vertices,
    polyline_vertices,
    spline_vertices,
)
from green.infrastructure.cad.dashes import chain_dashes
from green.infrastructure.cad.documents import (
    R12_NOTE,
    RESULT_MIN_VERSION,
    entity_layer,
    load_document,
)
from green.infrastructure.cad.ezdxf_fixes import install as install_ezdxf_fixes
from green.infrastructure.cad.hatch_footprint import bounded_hatch_footprint
from green.infrastructure.cad.hatch_geometry import GAP_CLOSED, HatchGeometryError, hatch_geometry
from green.infrastructure.cad.units import AUTO, decide_units

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.entities import DXFGraphic
    from ezdxf.layouts import BlockLayout
    from shapely.geometry.base import BaseGeometry

    from green.infrastructure.cad.documents import DocumentCache

install_ezdxf_fixes()

MAX_BLOCK_DEPTH = 8
# Исход примитива за рамкой обрезки XCLIP: CAD его не показывает, это не потеря.
CLIPPED = "clipped:outside"
# Починка геометрии без переосмысления: расхождение с нарисованным не больше этого (единицы
# чертежа) - та же линия, а не новая.
_EXACT_REPAIR = 1e-6
_HATCH_UNCERTAINTY_MIN_M = 0.002
# Контейнер, а не знак: обёртки MicroStation, выноски DIMTXT и анонимные блоки AutoCAD
# (*U, *D, *T), а также пустые, многолюдные и крупные блоки - листы и сборки, не значки.
CONTAINER_PREFIXES = ("msdelementtype", "dimtxt", "*")
SYMBOL_MAX_PRIMITIVES = 64
SYMBOL_MAX_SIZE_M = 12.0
_AREA_ENTITIES = frozenset({"HATCH", "MPOLYGON"})
_TEXT_ENTITIES = frozenset({"TEXT", "MTEXT", "ATTRIB"})
# Размер дугой и большой радиальный - такое же оформление, как DIMENSION (Харьковский проезд:
# 105 размеров ARC_DIMENSION раньше уходили в пробелы чтения).
ANNOTATIONS = frozenset(
    {
        "ATTDEF",
        "DIMENSION",
        "ARC_DIMENSION",
        "LARGE_RADIAL_DIMENSION",
        "TOLERANCE",
        "LEADER",
        "MULTILEADER",
        "VIEWPORT",
        "ACAD_TABLE",
    }
)
# Картинки под чертежом: растр (карта, спутник, скан), PDF/DWF/DGN-подложка, маска WIPEOUT,
# OLE-вставка. Объектов съёмки в них нет: они учитываются исходом и предупреждением и прогон
# не останавливают (решение пользователя 25.09.2026: незнакомое заменять правдоподобно).
UNDERLAYS = frozenset(
    {
        "IMAGE",
        "WIPEOUT",
        "OLE2FRAME",
        "PDFUNDERLAY",
        "PDFREFERENCE",
        "DWFUNDERLAY",
        "DWFREFERENCE",
        "DGNUNDERLAY",
        "DGNREFERENCE",
    }
)
_GAP_EXAMPLES = 5
# Починка самопересекающегося контура с площадью по правилу чёт-нечет (вопрос 1 пользователя).
_EVEN_ODD = "even-odd"
# Тип -> (пробел, если рисунок не разобрать; пробел, если рисунок пуст; исход при успехе).
_DRAWN = {
    "ACAD_PROXY_ENTITY": (
        "proxy-graphic-not-readable",
        "unsupported-spatial-entity",
        "proxy:graphic",
    ),
    "MLINE": ("mline-not-readable", "geometry-not-readable", "mline:lines"),
}
_SKIPPED = frozenset(
    {
        "ATTDEF",
        "DIMENSION",
        "ARC_DIMENSION",
        "LARGE_RADIAL_DIMENSION",
        "TOLERANCE",
        "LEADER",
        "MULTILEADER",
        "VIEWPORT",
        "3DSOLID",
        "BODY",
        "SURFACE",
        "MESH",
        "ACAD_PROXY_ENTITY",
        "ACAD_TABLE",
    }
)


# Тела 3D-чертежей: дом или сооружение моделью, а не контуром. На плане они - след (проекция
# граней), а не пробел чтения (синтетические участки других финалистов, 17.10.2026).
_VOLUMES = frozenset({"MESH", "3DSOLID", "BODY", "SURFACE"})
# Конечные объекты, которые вырожденными читаются точкой (нулевой радиус, длина, угол).
_POINT_LIKE = frozenset({"CIRCLE", "ARC", "LINE", "LWPOLYLINE", "POLYLINE", "ELLIPSE", "SPLINE"})


class EzdxfSceneReader:
    def __init__(
        self, *, flatten_distance_m: float = 0.1, documents: DocumentCache | None = None
    ) -> None:
        if not np.isfinite(flatten_distance_m) or flatten_distance_m <= 0:
            raise ValueError("Curve tolerance must be finite and positive")
        self._flatten = flatten_distance_m
        self._documents = documents

    def read(self, path: Path, *, unit: str = AUTO) -> Scene:
        digest = _sha256(path)
        doc, warnings = self._documents.load(path) if self._documents else load_document(path)
        units = decide_units(doc, unit)
        # Обход идёт в единицах чертежа, поэтому метровые пороги делятся на размер единицы.
        walker = _Walker(
            doc=doc,
            file_sha8=digest[:8],
            flatten=self._flatten / units.unit_m,
            unit_m=units.unit_m,
        )
        for entity in doc.modelspace():
            walker.visit(entity, parent_layer=None, chain=(), parent_handle="", index=0)
        features, labels, symbols = _to_metres(
            walker.features, walker.labels, walker.instances(), units.unit_m
        )
        _, hidden_diameter_labels, _ = _to_metres(
            [], walker.hidden_diameter_labels, [], units.unit_m
        )
        hidden_notes = (
            (
                (
                    f"Скрытые подписи диаметров: {len(hidden_diameter_labels)} сохранены только "
                    "для отступов от сетей; они не участвуют в определении покрытий."
                ),
            )
            if hidden_diameter_labels
            else ()
        )
        return Scene(
            source_name=path.name,
            source_sha256=digest,
            dxf_version=doc.dxfversion,
            features=features,
            labels=labels,
            warnings=(
                *warnings,
                *((R12_NOTE,) if doc.dxfversion < RESULT_MIN_VERSION else ()),
                *units.notes,
                *walker.warnings(),
                *hidden_notes,
            ),
            unit_m=units.unit_m,
            read_diagnostics=ReadDiagnostics(
                visited_by_type=dict(walker.visited),
                skipped_by_type=dict(walker.skipped),
                bounded_uncertainty_by_type=(
                    {"HATCH": walker.bounded_hatches} if walker.bounded_hatches else {}
                ),
                unresolved_xrefs=tuple(sorted(walker.unresolved_xrefs)),
                geometry_gaps=walker.geometry_gaps(),
                approximation_features=sum(bool(f.geometry_error_m) for f in features),
                max_approximation_error_m=max(
                    (f.geometry_error_m or 0.0 for f in features), default=0.0
                ),
                outcomes=dict(walker.outcomes),
            ),
            symbols=symbols,
            hidden_diameter_labels=hidden_diameter_labels,
        )


@dataclass(slots=True)
class _Walker:
    doc: Drawing
    file_sha8: str
    flatten: float
    unit_m: float = 1.0
    features: list[Feature] = field(default_factory=list)
    labels: list[TextLabel] = field(default_factory=list)
    hidden_diameter_labels: list[TextLabel] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    bounded_hatches: int = 0
    # Вырожденные объекты (нулевой радиус или длина, одна вершина), прочитанные точкой.
    degenerate: Counter[str] = field(default_factory=Counter)
    visited: Counter[str] = field(default_factory=Counter)
    unresolved_xrefs: set[str] = field(default_factory=set)
    gaps: Counter[tuple[str, str, str | None, str]] = field(default_factory=Counter)
    gap_refs: dict[tuple[str, str, str | None, str], list[str]] = field(default_factory=dict)
    # Учёт чтения: у каждого посещения ровно один исход.
    outcomes: Counter[str] = field(default_factory=Counter)
    symbols: list[SymbolInstance] = field(default_factory=list)
    strokes: Counter[str] = field(default_factory=Counter)
    sizes: dict[str, bbox.BoundingBox | None] = field(default_factory=dict)
    # Рамки обрезки XCLIP вставок, внутри которых идёт обход (единицы чертежа, WCS).
    clips: list[BaseGeometry] = field(default_factory=list)
    # Hidden inserts suppress their text, but keep physical constraint geometry.
    hidden_text_depth: int = 0
    hidden_layers: dict[str, str] | None = None
    # Тип линии вставок, внутри которых идёт обход: его берёт примитив с типом BYBLOCK.
    block_linetypes: list[str] = field(default_factory=list)
    # Тип линии слоя по имени слоя и наличие разрывов в типе линии (по имени в нижнем регистре).
    layer_linetypes: dict[str, str] | None = None
    patterned: dict[str, bool] | None = None

    def visit(  # noqa: PLR0913 - обход с явным учётом исходов
        self,
        entity: DXFGraphic,
        *,
        parent_layer: str | None,
        chain: tuple[str, ...],
        parent_handle: str,
        index: int,
        parent_block: str | None = None,
        owner: str | None = None,
    ) -> None:
        layer = decode_dxf_unicode(entity_layer(entity))
        if layer == "0" and parent_layer is not None:
            layer = parent_layer
        if parent_block is not None:
            parent_block = decode_dxf_unicode(parent_block)
        handle = entity.dxf.get("handle") or f"{parent_handle}~{index}"
        ref = SourceRef(self.file_sha8, _chain_hash(chain), handle)
        kind = entity.dxftype()
        self.visited[kind] += 1

        if kind in _TEXT_ENTITIES:
            outcome = self._label(entity, ref, layer, parent_block, chain, owner=owner)
        elif kind == "INSERT":
            outcome = self._insert(entity, ref, layer, chain, owner)  # ty: ignore[invalid-argument-type]
        elif kind == "MLINE" or (kind == "ACAD_PROXY_ENTITY" and entity.proxy_graphic):
            outcome = self._drawn(entity, ref, layer, chain=chain, block=parent_block, owner=owner)
        elif kind == "REGION":
            outcome = self._region(entity, ref, layer, parent_block, owner)  # ty: ignore[invalid-argument-type]
        elif kind in _VOLUMES or (
            isinstance(entity, Polyline) and (entity.is_poly_face_mesh or entity.is_polygon_mesh)
        ):
            outcome = self._volume(entity, ref, layer, parent_block, owner)
        elif kind in _SKIPPED or kind in UNDERLAYS:
            outcome = self._not_drawn(entity, layer, parent_block, ref)
        else:
            outcome = self._linework(entity, ref, layer, parent_block, owner)
        self.outcomes[outcome] += 1

    def _linework(
        self, entity: DXFGraphic, ref: SourceRef, layer: str, block: str | None, owner: str | None
    ) -> str:
        kind = entity.dxftype()
        # Починки контура штриховки (чёт-нечет, разрыв замкнут хордой) идут в исход объекта.
        repairs: tuple[str, ...] = ()
        uncertainty_footprint = None
        try:
            if kind in _AREA_ENTITIES:
                geometry, error, repairs = hatch_geometry(entity, self.flatten)  # ty: ignore[invalid-argument-type]
                uncertainty_footprint = (
                    self._hatch_uncertainty(entity, error, repairs) if kind == "HATCH" else None
                )
            else:
                geometry, error = self._geometry(entity)
        except HatchGeometryError as exc:
            return self._skip(kind, layer, block, str(exc), ref)
        degenerate = geometry is None or geometry.is_empty
        if degenerate:
            geometry, error = self._point_of(entity), 0.0
        if geometry is None:
            return self._skip(kind, layer, block, "geometry-not-readable", ref)
        if not np.isfinite(shapely.get_coordinates(geometry)).all():
            return self._skip(kind, layer, block, "non-finite-coordinates", ref)
        geometry, error, repairs = _repaired(geometry, error, repairs)
        visible = self._inside_clips(geometry, uncertainty_footprint)
        if visible is None:
            return CLIPPED
        clipped = visible[0] is not geometry
        geometry, uncertainty_footprint = visible
        if error is None:
            self._gap(kind, layer, block, "approximation-error-not-bounded", ref)
        # Срезанный рамкой круг - уже не крона и не ствол целиком.
        whole_circle = kind == "CIRCLE" and not clipped and not degenerate
        radius = abs(entity.dxf.radius) * self.unit_m if whole_circle else None
        center = entity.ocs().to_wcs(entity.dxf.center) if whole_circle else None
        self._feature(
            Feature(
                ref=ref,
                layer=layer,
                geometry=geometry,
                block=block,
                circle_radius_m=radius,
                geometry_error_m=error * self.unit_m if error is not None else None,
                source_entity_type=kind,
                uncertainty_footprint=uncertainty_footprint,
                circle_center_m=(center.x * self.unit_m, center.y * self.unit_m)
                if center is not None
                else None,
                symbol=owner,
                dashed=kind not in _AREA_ENTITIES and self._dashed(entity, layer),
            )
        )
        self.bounded_hatches += int(uncertainty_footprint is not None)
        # Починенный контур не молчит: исход несёт вид починки (feature:hatch-even-odd).
        return "feature:" + "+".join(repairs) if repairs else "feature"

    def _inside_clips(
        self, geometry: BaseGeometry, footprint: BaseGeometry | None
    ) -> tuple[BaseGeometry, BaseGeometry | None] | None:
        """Часть внутри рамок обрезки XCLIP; None - объект целиком срезан."""
        if not self.clips:
            return geometry, footprint
        visible = self._clip(geometry)
        if visible.is_empty:
            return None
        if footprint is not None:
            footprint = self._clip(footprint)
            if footprint.is_empty:
                footprint = None
        return visible, footprint

    def _point_of(self, entity: DXFGraphic) -> Point | None:
        """Круг нулевого радиуса, дуга нулевого угла, полилиния из одной вершины - метка в
        точке (колодец, опора), а не потерянная геометрия."""
        point = _anchor_point(entity)
        if point is not None:
            self.degenerate[entity.dxftype()] += 1
        return point

    def _hatch_uncertainty(
        self, entity: DXFGraphic, error: float, repairs: tuple[str, ...]
    ) -> BaseGeometry | None:
        if GAP_CLOSED not in repairs or error * self.unit_m <= _HATCH_UNCERTAINTY_MIN_M:
            return None
        footprint = bounded_hatch_footprint(entity, self.flatten)  # ty: ignore[invalid-argument-type]
        if footprint is None:
            raise HatchGeometryError("hatch-footprint-unbounded")
        return footprint

    def _visible(self, point: Point) -> bool:
        return all(region.covers(point) for region in self.clips)

    def _clip(self, geometry: BaseGeometry) -> BaseGeometry:
        """Видимая часть внутри всех рамок; тот же объект, если он целиком внутри."""
        for region in self.clips:
            if region.covers(geometry):
                continue
            geometry = _same_dimension(geometry, geometry.intersection(region))
            if geometry.is_empty:
                break
        return geometry

    def _drawn(  # noqa: PLR0913 - как у вставки: слой, цепочка, блок и владелец-знак
        self,
        entity: DXFGraphic,
        ref: SourceRef,
        layer: str,
        *,
        chain: tuple[str, ...],
        block: str | None,
        owner: str | None,
    ) -> str:
        """Объект, который CAD рисует набором примитивов, читается ими, как вставка: прокси-объект
        стороннего приложения - по своему рисунку, мультилиния - линиями стиля на смещениях от
        оси. Примитивы на слое «0» получают слой объекта. Документ не меняется."""
        kind = entity.dxftype()
        unreadable, empty, outcome = _DRAWN[kind]
        try:
            children = list(entity.virtual_entities())  # ty: ignore[unresolved-attribute]
        except ValueError, TypeError, ArithmeticError, IndexError, struct.error:
            return self._skip(kind, layer, block, unreadable, ref)
        if not children:
            return self._skip(kind, layer, block, empty, ref)
        for position, child in enumerate(children):
            self.visit(
                child,
                parent_layer=layer,
                chain=chain,
                parent_handle=ref.handle,
                index=position,
                parent_block=block,
                owner=owner,
            )
        return outcome

    def _not_drawn(self, entity: DXFGraphic, layer: str, block: str | None, ref: SourceRef) -> str:
        """Объект без геометрии для расчёта: подложка, оформление или пробел с причиной."""
        kind = entity.dxftype()
        self.skipped[kind] += 1
        if kind in UNDERLAYS:
            return f"skipped:{kind}:underlay"
        if kind in ANNOTATIONS:
            return f"skipped:{kind}:annotation"
        reason = "unsupported-spatial-entity"
        if isinstance(entity, Body) and not entity.acis_data:
            reason = "missing-acis-data"
        self._gap(kind, layer, block, reason, ref)
        return f"skipped:{kind}:{reason}"

    def _skip(self, kind: str, layer: str, block: str | None, reason: str, ref: SourceRef) -> str:
        self.skipped[kind] += 1
        self._gap(kind, layer, block, reason, ref)
        return f"skipped:{kind}:{reason}"

    def _feature(self, feature: Feature) -> None:
        self.features.append(feature)
        if feature.symbol is not None:
            self.strokes[feature.symbol] += 1

    def _region(
        self, entity: Body, ref: SourceRef, layer: str, block: str | None, owner: str | None
    ) -> str:
        """REGION: форма в ACIS. Внутри вставки ezdxf оставляет матрицу вставки при копии."""
        matrix = entity.temporary_transformation().get_matrix()
        try:
            geometry, error = region_polygon(entity, matrix, self.flatten)
        except RegionGeometryError as exc:
            return self._skip("REGION", layer, block, exc.reason, ref)
        if self.clips:
            geometry = self._clip(geometry)
            if geometry.is_empty:
                return CLIPPED
        self._feature(
            Feature(
                ref=ref,
                layer=layer,
                geometry=geometry,
                block=block,
                geometry_error_m=error * self.unit_m,
                source_entity_type="REGION",
                symbol=owner,
            )
        )
        return "feature"

    def _volume(
        self, entity: DXFGraphic, ref: SourceRef, layer: str, block: str | None, owner: str | None
    ) -> str:
        """Тело - след на плане: объединение проекций граней. Не вышло - пробел с причиной."""
        kind = entity.dxftype()
        try:
            if kind == "MESH":
                geometry, error = _mesh_footprint(entity.vertices, entity.faces), 0.0  # ty: ignore[unresolved-attribute]
            elif kind == "POLYLINE":
                mesh = MeshBuilder.from_polyface(entity)  # ty: ignore[invalid-argument-type]
                geometry, error = _mesh_footprint(mesh.vertices, mesh.faces), 0.0  # ty: ignore[invalid-argument-type]
            else:
                matrix = entity.temporary_transformation().get_matrix()  # ty: ignore[unresolved-attribute]
                geometry, error = region_polygon(entity, matrix, self.flatten, footprint=True)  # ty: ignore[invalid-argument-type]
        except RegionGeometryError as exc:
            return self._not_drawn_reason(entity, layer, block, ref, exc.reason)
        if geometry.is_empty or geometry.area <= 0:
            return self._not_drawn_reason(entity, layer, block, ref, "no-plan-footprint")
        if self.clips:
            geometry = self._clip(geometry)
            if geometry.is_empty:
                return CLIPPED
        self._feature(
            Feature(
                ref=ref,
                layer=layer,
                geometry=geometry,
                block=block,
                geometry_error_m=error * self.unit_m,
                source_entity_type=kind,
                symbol=owner,
            )
        )
        return "feature"

    def _not_drawn_reason(
        self, entity: DXFGraphic, layer: str, block: str | None, ref: SourceRef, reason: str
    ) -> str:
        kind = entity.dxftype()
        self.skipped[kind] += 1
        self._gap(kind, layer, block, reason, ref)
        return f"skipped:{kind}:{reason}"

    def _gap(self, kind: str, layer: str, block: str | None, reason: str, ref: SourceRef) -> None:
        key = (kind, layer, block, reason)
        self.gaps[key] += 1
        examples = self.gap_refs.setdefault(key, [])
        if len(examples) < _GAP_EXAMPLES:
            examples.append(str(ref))

    def geometry_gaps(self) -> tuple[GeometryGap, ...]:
        return tuple(
            GeometryGap(kind, layer, block, reason, count, tuple(self.gap_refs[key]))
            for key, count in self.gaps.items()
            for kind, layer, block, reason in [key]
        )

    def _insert(
        self, insert: Insert, ref: SourceRef, layer: str, chain: tuple[str, ...], owner: str | None
    ) -> str:
        if insert.mcount > 1:
            for position, instance in enumerate(insert.multi_insert()):
                instance_ref = replace(ref, handle=f"{ref.handle}@{position}")
                self._insert(instance, instance_ref, layer, chain, owner)
            return "insert:multi"
        clip = XClip(insert)
        region = None
        if clip.has_clipping_path and clip.is_clipping_enabled:
            # virtual_entities() не знает обрезки, а блок целиком придумал бы грунт за
            # рамкой: разобранное режется той же рамкой, что показывает CAD.
            region = clip_region(clip)
            if region is None:
                self.skipped["INSERT:XCLIP"] += 1
                self._gap("INSERT", layer, insert.dxf.name, "XCLIP-inverted-not-applied", ref)
                return "insert:xclip"
        name = insert.dxf.name
        block = self.doc.blocks.get(name)
        if block is None or block.block is None:
            self.skipped["INSERT:no-block"] += 1
            return "insert:no-block"
        if (block.block.is_xref or block.block.is_xref_overlay) and len(block) == 0:
            self.unresolved_xrefs.add(name)
            return "insert:xref-unresolved"
        refused = self._too_deep(name, chain)
        if refused is not None:
            return refused
        return self._placed(
            insert, block, ref, layer, chain=(*chain, name), owner=owner, region=region
        )

    def _too_deep(self, name: str, chain: tuple[str, ...]) -> str | None:
        """Вставка, которую обход не разбирает: блок внутри самого себя (цикл ссылок, его
        объекты уже учтены на этом пути) или вложенность глубже MAX_BLOCK_DEPTH."""
        if name in chain:
            self.skipped["INSERT:cycle"] += 1
            return "insert:cycle"
        if len(chain) >= MAX_BLOCK_DEPTH:
            self.skipped["INSERT:too-deep"] += 1
            return "insert:too-deep"
        return None

    def _placed(  # noqa: PLR0913 - вставка, её блок и место в обходе
        self,
        insert: Insert,
        block: BlockLayout,
        ref: SourceRef,
        layer: str,
        *,
        chain: tuple[str, ...],
        owner: str | None,
        region: BaseGeometry | None,
    ) -> str:
        """Роль и разбор вставки внутри её рамки обрезки, если рамка есть."""
        if region is not None:
            self.clips.append(region)
        self.block_linetypes.append(self._linetype(insert, layer))
        hidden = (
            bool(insert.dxf.get("invisible", 0)) or self._hidden_layer_reason(layer) is not None
        )
        self.hidden_text_depth += int(hidden)
        try:
            outcome, child_owner = self._role(insert, block, ref, layer, owner)
            if outcome == CLIPPED:
                return outcome
            if not self._explode(insert, ref, layer, chain, child_owner):
                self.skipped["INSERT:not-explodable"] += 1
                return "insert:not-explodable"
            return outcome
        finally:
            self.hidden_text_depth -= int(hidden)
            self.block_linetypes.pop()
            if region is not None:
                self.clips.pop()

    def _role(
        self, insert: Insert, block: BlockLayout, ref: SourceRef, layer: str, owner: str | None
    ) -> tuple[str, str | None]:
        """Исход вставки и владелец её детей.

        Экземпляр знака создаётся до обхода детей: они получают его как владельца. Вставка
        внутри знака - часть его рисунка, а не второй знак.
        """
        if owner is not None:
            return "insert:in-symbol", owner
        if self._is_container(insert, block):
            return "insert:container", None
        point = insert.ocs().to_wcs(insert.dxf.insert)
        if self.clips and not self._visible(Point(point.x, point.y)):
            return CLIPPED, None
        self.symbols.append(
            SymbolInstance(
                ref=ref,
                block=decode_dxf_unicode(insert.dxf.name),
                layer=layer,
                x=point.x,
                y=point.y,
                rotation_deg=float(insert.dxf.get("rotation", 0.0)),
                scale=float(insert.dxf.get("xscale", 1.0)),
            )
        )
        return "insert:symbol", str(ref)

    def _explode(
        self, insert: Insert, ref: SourceRef, layer: str, chain: tuple[str, ...], owner: str | None
    ) -> bool:
        name = chain[-1]
        for position, attribute in enumerate(insert.attribs):
            # Attached values are instance data, not the ATTDEF default. Copying
            # removes the handle so MINSERT instances get distinct source refs.
            self.visit(
                attribute.copy(),
                parent_layer=layer,
                chain=chain,
                parent_handle=f"{ref.handle}/attrib",
                index=position,
                parent_block=name,
                owner=owner,
            )
        try:
            children = list(insert.virtual_entities(skipped_entity_callback=self._virtual_skip))
        except ValueError, TypeError, ArithmeticError:
            return False
        start = len(self.features)
        for position, child in enumerate(children):
            self.visit(
                child,
                parent_layer=layer,
                chain=chain,
                parent_handle=ref.handle,
                index=position,
                parent_block=name,
                owner=owner,
            )
        if owner is None:
            # Пунктир, разобранный на штрихи (MicroStation): штрихи одной линии идут подряд и
            # сшиваются обратно в линию. Исходы штрихов в учёте чтения остаются как были.
            self.features[start:] = chain_dashes(
                self.features[start:], parent=ref.handle, unit_m=self.unit_m
            )
        return True

    def _dashed(self, entity: DXFGraphic, layer: str) -> bool:
        """Тип линии с разрывами: у сущности, по слою (BYLAYER) или по вставке (BYBLOCK)."""
        if self.patterned is None:
            self.patterned = {
                str(record.dxf.name).casefold(): _has_gaps(record) for record in self.doc.linetypes
            }
        return self.patterned.get(self._linetype(entity, layer).casefold(), False)

    def _linetype(self, entity: DXFGraphic, layer: str) -> str:
        name = str(entity.dxf.get("linetype", "BYLAYER"))
        key = name.casefold()
        if key == "byblock":
            return self.block_linetypes[-1] if self.block_linetypes else "CONTINUOUS"
        if key != "bylayer":
            return name
        if self.layer_linetypes is None:
            self.layer_linetypes = {
                decode_dxf_unicode(str(record.dxf.name)): str(record.dxf.get("linetype", ""))
                for record in self.doc.layers
            }
        return self.layer_linetypes.get(layer, "CONTINUOUS")

    def _is_container(self, insert: Insert, block: BlockLayout) -> bool:
        """Контейнер - обёртка или сборка, а не значок: знак - то, что внутри неё."""
        if local_name(decode_dxf_unicode(block.name)).casefold().startswith(CONTAINER_PREFIXES):
            return True
        if len(block) > SYMBOL_MAX_PRIMITIVES:
            return True
        size = self._block_size(block)
        if size is None:
            return True
        scale = max(abs(insert.dxf.get("xscale", 1.0)), abs(insert.dxf.get("yscale", 1.0)))
        return size * scale * self.unit_m > SYMBOL_MAX_SIZE_M

    def _block_size(self, block: BlockLayout) -> float | None:
        """Наибольший размер рисунка блока в его единицах; None - пустой или неизмеримый."""
        box = self._block_box(block, depth=0)
        return max(box.size.x, box.size.y) if box is not None and box.has_data else None

    def _block_box(self, block: BlockLayout, depth: int) -> bbox.BoundingBox | None:
        """Габарит рисунка блока без разборки аннотаций.

        bbox.extents разбирает выноски и размеры на примитивы и при этом создаёт в документе
        блоки стрелок, а чтение не меняет исходный документ. Поэтому аннотации пропускаются,
        а вложенные вставки обходятся здесь же, с их матрицей.
        """
        if block.name in self.sizes:
            return self.sizes[block.name]
        box = bbox.BoundingBox()
        self.sizes[block.name] = None  # защита от цикла вставок
        for entity in block:
            kind = entity.dxftype()
            if kind in ANNOTATIONS:
                continue
            if not isinstance(entity, Insert):
                box.extend(bbox.extents([entity], fast=True))
                continue
            inner = self.doc.blocks.get(entity.dxf.name)
            if inner is None or depth >= MAX_BLOCK_DEPTH:
                continue
            inner_box = self._block_box(inner, depth + 1)
            if inner_box is None or not inner_box.has_data:
                continue
            (x0, y0, _), (x1, y1, _) = inner_box.extmin, inner_box.extmax
            corners = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]
            instances = entity.multi_insert() if entity.mcount > 1 else [entity]
            for instance in instances:
                box.extend(instance.matrix44().transform_vertices(corners))
        self.sizes[block.name] = box if box.has_data else None
        return self.sizes[block.name]

    def instances(self) -> list[SymbolInstance]:
        return [replace(s, strokes=self.strokes[str(s.ref)]) for s in self.symbols]

    def _virtual_skip(self, entity: DXFGraphic, reason: str) -> None:
        self.skipped[f"VIRTUAL:{entity.dxftype()}:{reason}"] += 1

    def _hidden_layer_reason(self, layer: str) -> str | None:
        if self.hidden_layers is None:
            self.hidden_layers = {}
            for record in self.doc.layers:
                reason = (
                    "layer-frozen"
                    if record.is_frozen()
                    else "layer-off"
                    if record.is_off()
                    else None
                )
                if reason is not None:
                    name = decode_dxf_unicode(str(record.dxf.name)).casefold()
                    self.hidden_layers[name] = reason
        return self.hidden_layers.get(layer.casefold())

    def _hidden_text_reason(self, entity: DXFGraphic, layer: str) -> str | None:
        # DXF group 60 applies to all text; ATTRIB also has its own group 70 bit.
        if entity.dxf.get("invisible", 0):
            return "invisible"
        if isinstance(entity, Attrib) and entity.is_invisible:
            return "invisible-attribute"
        return "invisible-parent" if self.hidden_text_depth else self._hidden_layer_reason(layer)

    def _label(  # noqa: PLR0913 - подпись с владельцем-знаком
        self,
        entity: DXFGraphic,
        ref: SourceRef,
        layer: str,
        block: str | None,
        chain: tuple[str, ...],
        *,
        owner: str | None,
    ) -> str:
        reason = self._hidden_text_reason(entity, layer)
        # CIF escapes are not decoded by ezdxf on load, including R2007+.
        # Decode before stripping MTEXT control sequences, only in our scene;
        # keep the source Drawing unchanged for export and integrity checks.
        if isinstance(entity, MText):
            text = str(fast_plain_mtext(decode_dxf_unicode(entity.text)))
        else:
            text = plain_text(decode_dxf_unicode(entity.dxf.text))
        if reason is not None and parse_diameter_m(text) is None:
            self.skipped[f"{entity.dxftype()}:{reason}"] += 1
            return f"skipped:{entity.dxftype()}:{reason}"
        if not text or not text.strip():
            return "label:empty"
        original = entity.origin_of_copy or entity
        if (
            isinstance(original, Text)
            and (original.dxf.halign or original.dxf.valign)
            and not original.dxf.hasattr("align_point")
        ):
            # Text.transform() supplies a fallback before virtual_entities()
            # returns. Inspect the original too, or blocks hide missing data.
            return self._skip(entity.dxftype(), layer, block, "text-alignment-point-missing", ref)
        point = entity.dxf.insert
        second = None
        if isinstance(entity, Text):
            # For justified TEXT/ATTRIB, DXF group 10 may be stale or ignored;
            # group 11 is its declared anchor. LEFT/FIT/ALIGNED retain p1.
            _, point, second = entity.get_placement()
            point = entity.ocs().to_wcs(point)
        if not np.isfinite(tuple(point)).all() or (
            second is not None and not np.isfinite(tuple(second)).all()
        ):
            return self._skip(entity.dxftype(), layer, block, "non-finite-text-coordinates", ref)
        if self.clips and not self._visible(Point(point.x, point.y)):
            return CLIPPED
        target = self.hidden_diameter_labels if reason is not None else self.labels
        target.append(
            TextLabel(
                ref=ref,
                layer=layer,
                x=point.x,
                y=point.y,
                text=text.strip(),
                block=block,
                surface_role="ignore" if reason is not None else "auto",
                block_chain=tuple(decode_dxf_unicode(name) for name in chain),
                symbol=owner,
            )
        )
        if owner is not None and reason is None:
            self.strokes[owner] += 1
        return f"label:hidden-diameter:{reason}" if reason is not None else "label"

    def _geometry(self, entity: DXFGraphic) -> tuple[BaseGeometry | None, float | None]:  # noqa: C901, PLR0911 - one branch per entity type
        kind = entity.dxftype()
        try:
            if kind == "LINE":
                start, end = entity.dxf.start, entity.dxf.end
                return LineString([(start.x, start.y), (end.x, end.y)]), 0.0
            if kind == "POINT":
                location = entity.dxf.location
                return Point(location.x, location.y), 0.0
            if isinstance(entity, Circle):
                # ARC inherits Circle but is open: closing it would invent a
                # chord and a filled area, including false positive lawn evidence.
                vertices, tolerance = circle_vertices(entity, self.flatten)
                points = [(v.x, v.y) for v in vertices]
                return _polyline(points, closed=kind == "CIRCLE"), tolerance
            if isinstance(entity, Ellipse):
                points, closed = ellipse_vertices(entity, self.flatten)
                return _polyline(points, closed=closed), self.flatten
            if isinstance(entity, LWPolyline) and not entity.has_arc:
                points = [(v.x, v.y) for v in entity.vertices_in_wcs()]
                return _polyline(points, closed=entity.closed), 0.0
            if isinstance(entity, LWPolyline) or (
                isinstance(entity, Polyline) and entity.is_2d_polyline
            ):
                if isinstance(entity, Polyline) and (fitted := fitted_vertices(entity)):
                    # Сглажена сплайном: на экране CAD ломаная по вершинам сглаживания.
                    return _polyline(fitted, closed=entity.is_closed), 0.0
                points, error = polyline_vertices(entity, self.flatten)
                if isinstance(entity, Polyline) and entity.dxf.flags & 4:
                    # Сглажена сплайном, но вершины сглаживания не читаются (дуги у них):
                    # что рисует CAD, не установлено. Сглаживание дугами (флаг 2) - та же
                    # ломаная с дугами через все вершины, её погрешность ограничена.
                    error = None
                return _polyline(points, closed=entity.is_closed), error
            if isinstance(entity, Spline) and (bounded := self._spline(entity)) is not None:
                return bounded
            path = make_path(entity)
            vertices = [(v.x, v.y) for v in path.flattening(self.flatten)]
        except HatchGeometryError:
            raise
        except TypeError, ValueError, ArithmeticError, AttributeError:
            return None, None
        return _polyline(vertices, closed=path.is_closed), None if path.has_curves else 0.0

    def _spline(self, entity: Spline) -> tuple[BaseGeometry | None, float] | None:
        """Сплайн с контрольными точками - с доказанной погрешностью; иначе None, и он идёт
        общим путём с неограниченной погрешностью (пробел)."""
        try:
            points, error = spline_vertices(entity, self.flatten)
        except ValueError:
            return None
        return _polyline(points, closed=entity.closed), error

    def warnings(self) -> list[str]:
        messages = []
        if self.unresolved_xrefs:
            names = ", ".join(sorted(self.unresolved_xrefs)[:10])
            messages.append(
                f"Внешние ссылки не загружены ({len(self.unresolved_xrefs)}): {names}. "
                "Объекты из них не учтены, сети могли быть потеряны."
            )
        if self.skipped:
            details = ", ".join(f"{k}: {v}" for k, v in self.skipped.most_common(8))
            messages.append(f"Пропущены сущности без геометрии для расчёта: {details}")
        if self.degenerate:
            details = ", ".join(f"{k}: {v}" for k, v in self.degenerate.most_common(8))
            messages.append(
                "Вырожденные объекты (нулевой радиус или длина, одна вершина) прочитаны точкой: "
                f"{details}."
            )
        if self.bounded_hatches:
            messages.append(
                f"HATCH с большим разрывом контура: {self.bounded_hatches}; "
                "материал в ограниченной области не подтверждён, посадки там исключены."
            )
        return messages


def clip_region(clip: XClip) -> BaseGeometry | None:
    """Видимая область обычной обрезки в WCS; None - инвертированная или вырожденная."""
    path = clip.get_wcs_clipping_path()
    if clip.is_inverted_clip or path.is_inverted_clip or len(path.vertices) < 3:  # noqa: PLR2004 - многоугольник
        return None
    area = shapely.make_valid(Polygon([(v.x, v.y) for v in path.vertices]))
    return area if area.area > 0 else None


def _same_dimension(original: BaseGeometry, clipped: BaseGeometry) -> BaseGeometry:
    """Пересечение с рамкой без осколков меньшей размерности (касание - не рисунок)."""
    dimension = shapely.get_dimensions(original)
    parts = [p for p in shapely.get_parts(clipped) if shapely.get_dimensions(p) == dimension]
    while any(p.geom_type == "GeometryCollection" for p in parts):
        parts = [q for p in parts for q in shapely.get_parts(p)]
    kept = [p for p in parts if shapely.get_dimensions(p) == dimension]
    return shapely.union_all(kept) if kept else shapely.Point()


def _same_ink(drawn: BaseGeometry, repaired: BaseGeometry) -> bool:
    """Починка ничего не переосмыслила: линии починенного - те же чернила, что нарисованы.

    Отрезок нулевой длины становится точкой, сложенный контур нулевой площади - линией.
    Самопересекающийся контур с площадью («восьмёрка») - заливка по правилу чёт-нечет, как у
    штриховки (решение пользователя 25.09.2026, вопрос 1): границы частей заливки - те же
    линии контура, узлы только в точках самопересечения. Погрешность остаётся прежней.
    """
    lines = shapely.boundary(drawn) if drawn.geom_type in {"Polygon", "MultiPolygon"} else drawn
    return shapely.hausdorff_distance(lines, _ink(repaired)) <= _EXACT_REPAIR


def _ink(geometry: BaseGeometry) -> BaseGeometry:
    """Чернила геометрии: у площадей - их границы, линии и точки - как есть."""
    parts = list(shapely.get_parts(geometry))
    while any(part.geom_type in {"GeometryCollection", "MultiPolygon"} for part in parts):
        parts = [p for part in parts for p in shapely.get_parts(part)]
    return shapely.union_all(
        [part.boundary if part.geom_type == "Polygon" else part for part in parts]
    )


def _repaired(
    geometry: BaseGeometry, error: float | None, repairs: tuple[str, ...]
) -> tuple[BaseGeometry, float | None, tuple[str, ...]]:
    """Недопустимая геометрия чинится без смены чернил, иначе погрешность не ограничена."""
    if geometry.is_valid:
        return geometry, error, repairs
    repaired = shapely.make_valid(geometry)
    if not _same_ink(geometry, repaired):
        return repaired, None, repairs
    if _has_area(repaired):
        return repaired, error, (*repairs, _EVEN_ODD)
    return repaired, error, repairs


def _has_area(geometry: BaseGeometry) -> bool:
    return geometry.area > 0


def _has_gaps(record: Linetype) -> bool:
    """В рисунке типа линии есть разрыв: dash, gap, dash, gap... с положительным gap."""
    try:
        pattern = record.simplified_line_pattern()
    except AttributeError, TypeError, ValueError, IndexError:
        return False
    return any(value > 0 for value in pattern[1::2])


def _to_metres(
    features: list[Feature], labels: list[TextLabel], symbols: list[SymbolInstance], unit_m: float
) -> tuple[tuple[Feature, ...], tuple[TextLabel, ...], tuple[SymbolInstance, ...]]:
    """Сцена в метрах: дальше по коду все пороги и нормы метровые."""
    if unit_m == 1.0:
        return tuple(features), tuple(labels), tuple(symbols)
    scaled = shapely.transform(
        np.asarray([f.geometry for f in features], dtype=object), lambda xy: xy * unit_m
    )
    return (
        tuple(
            replace(
                feature,
                geometry=geometry,
                uncertainty_footprint=(
                    shapely.transform(feature.uncertainty_footprint, lambda xy: xy * unit_m)
                    if feature.uncertainty_footprint is not None
                    else None
                ),
            )
            for feature, geometry in zip(features, scaled, strict=True)
        ),
        tuple(replace(label, x=label.x * unit_m, y=label.y * unit_m) for label in labels),
        tuple(replace(symbol, x=symbol.x * unit_m, y=symbol.y * unit_m) for symbol in symbols),
    )


def _polyline(points: list[tuple[float, float]], *, closed: bool) -> BaseGeometry | None:
    unique = list(dict.fromkeys(points))
    if closed and len(unique) >= 3:  # noqa: PLR2004 - polygon needs three vertices
        return Polygon(points)
    if len(unique) >= 2:  # noqa: PLR2004 - line needs two vertices
        return LineString(points)
    return Point(points[0]) if points else None


def _anchor_point(entity: DXFGraphic) -> Point | None:
    """Точка вырожденного объекта: центр круга и дуги, начало отрезка, первая вершина.

    Только у конечных объектов: XLINE и RAY бесконечны, их точка - не место на плане."""
    if entity.dxftype() not in _POINT_LIKE:
        return None
    if isinstance(entity, Arc):
        start = entity.start_point
        return Point(start.x, start.y)
    dxf = entity.dxf
    for name in ("center", "start", "insert", "location"):
        if dxf.hasattr(name):
            point = dxf.get(name)
            if name in {"center", "insert"} and entity.dxf.hasattr("extrusion"):
                point = entity.ocs().to_wcs(point)
            return Point(point.x, point.y)
    if isinstance(entity, LWPolyline) and len(entity):
        first = next(iter(entity.vertices_in_wcs()))
        return Point(first.x, first.y)
    return None


def _chain_hash(chain: tuple[str, ...]) -> str:
    if not chain:
        return NO_XREF
    return hashlib.sha256("/".join(chain).encode()).hexdigest()[:8]


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _mesh_footprint(
    vertices: Iterable[Sequence[float]], faces: Iterable[Sequence[int]]
) -> Polygon | BaseGeometry:
    """Объединение проекций граней сетки на план; вертикальные грани площади не дают."""
    vertices = list(vertices)
    polygons = []
    for face in faces:
        ring = [(vertices[i][0], vertices[i][1]) for i in face]
        if len(ring) >= 3:  # noqa: PLR2004 - треугольник
            polygon = shapely.make_valid(Polygon(ring))
            if polygon.area > 0:
                polygons.append(polygon)
    if not polygons:
        return Polygon()
    return shapely.union_all(polygons)
