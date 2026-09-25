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
from ezdxf.entities import Body, Circle, Ellipse, Insert, LWPolyline, MText, Polyline, Spline, Text
from ezdxf.lldxf.encoding import decode_dxf_unicode
from ezdxf.path import make_path
from ezdxf.tools.text import fast_plain_mtext, plain_text
from ezdxf.xclip import XClip
from shapely.geometry import LineString, Point, Polygon

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
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.ezdxf_fixes import install as install_ezdxf_fixes
from green.infrastructure.cad.hatch_geometry import HatchGeometryError, hatch_geometry
from green.infrastructure.cad.units import AUTO, decide_units

if TYPE_CHECKING:
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
        return Scene(
            source_name=path.name,
            source_sha256=digest,
            dxf_version=doc.dxfversion,
            features=features,
            labels=labels,
            warnings=(*warnings, *units.notes, *walker.warnings()),
            unit_m=units.unit_m,
            read_diagnostics=ReadDiagnostics(
                visited_by_type=dict(walker.visited),
                skipped_by_type=dict(walker.skipped),
                unresolved_xrefs=tuple(sorted(walker.unresolved_xrefs)),
                geometry_gaps=walker.geometry_gaps(),
                approximation_features=sum(bool(f.geometry_error_m) for f in features),
                max_approximation_error_m=max(
                    (f.geometry_error_m or 0.0 for f in features), default=0.0
                ),
                outcomes=dict(walker.outcomes),
            ),
            symbols=symbols,
        )


@dataclass(slots=True)
class _Walker:
    doc: Drawing
    file_sha8: str
    flatten: float
    unit_m: float = 1.0
    features: list[Feature] = field(default_factory=list)
    labels: list[TextLabel] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
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
        layer = decode_dxf_unicode(entity.dxf.get("layer", "0"))
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
        try:
            if kind in _AREA_ENTITIES:
                geometry, error, repairs = hatch_geometry(entity, self.flatten)  # ty: ignore[invalid-argument-type]
            else:
                geometry, error = self._geometry(entity)
        except HatchGeometryError as exc:
            return self._skip(kind, layer, block, str(exc), ref)
        if geometry is None or geometry.is_empty:
            return self._skip(kind, layer, block, "geometry-not-readable", ref)
        if not np.isfinite(shapely.get_coordinates(geometry)).all():
            return self._skip(kind, layer, block, "non-finite-coordinates", ref)
        geometry, error, repairs = _repaired(geometry, error, repairs)
        clipped = False
        if self.clips:
            visible = self._clip(geometry)
            if visible.is_empty:
                return CLIPPED
            clipped = visible is not geometry
            geometry = visible
        if error is None:
            self._gap(kind, layer, block, "approximation-error-not-bounded", ref)
        # Срезанный рамкой круг - уже не крона и не ствол целиком.
        radius = abs(entity.dxf.radius) * self.unit_m if kind == "CIRCLE" and not clipped else None
        center = (
            entity.ocs().to_wcs(entity.dxf.center) if kind == "CIRCLE" and not clipped else None
        )
        self._feature(
            Feature(
                ref=ref,
                layer=layer,
                geometry=geometry,
                block=block,
                circle_radius_m=radius,
                geometry_error_m=error * self.unit_m if error is not None else None,
                source_entity_type=kind,
                circle_center_m=(center.x * self.unit_m, center.y * self.unit_m)
                if center is not None
                else None,
                symbol=owner,
            )
        )
        # Починенный контур не молчит: исход несёт вид починки (feature:hatch-even-odd).
        return "feature:" + "+".join(repairs) if repairs else "feature"

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
        if len(chain) >= MAX_BLOCK_DEPTH:
            self.skipped["INSERT:too-deep"] += 1
            return "insert:too-deep"
        return self._placed(
            insert, block, ref, layer, chain=(*chain, name), owner=owner, region=region
        )

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
        try:
            outcome, child_owner = self._role(insert, block, ref, layer, owner)
            if outcome == CLIPPED:
                return outcome
            if not self._explode(insert, ref, layer, chain, child_owner):
                self.skipped["INSERT:not-explodable"] += 1
                return "insert:not-explodable"
            return outcome
        finally:
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
        return True

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
        # CIF escapes are not decoded by ezdxf on load, including R2007+.
        # Decode before stripping MTEXT control sequences, only in our scene;
        # keep the source Drawing unchanged for export and integrity checks.
        if isinstance(entity, MText):
            text = str(fast_plain_mtext(decode_dxf_unicode(entity.text)))
        else:
            text = plain_text(decode_dxf_unicode(entity.dxf.text))
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
        self.labels.append(
            TextLabel(
                ref=ref,
                layer=layer,
                x=point.x,
                y=point.y,
                text=text.strip(),
                block=block,
                block_chain=tuple(decode_dxf_unicode(name) for name in chain),
                symbol=owner,
            )
        )
        if owner is not None:
            self.strokes[owner] += 1
        return "label"

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
            replace(feature, geometry=geometry)
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


def _chain_hash(chain: tuple[str, ...]) -> str:
    if not chain:
        return NO_XREF
    return hashlib.sha256("/".join(chain).encode()).hexdigest()[:8]


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()
