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
# Контейнер, а не знак: обёртки MicroStation, выноски DIMTXT и анонимные блоки AutoCAD
# (*U, *D, *T), а также пустые, многолюдные и крупные блоки - листы и сборки, не значки.
CONTAINER_PREFIXES = ("msdelementtype", "dimtxt", "*")
SYMBOL_MAX_PRIMITIVES = 64
SYMBOL_MAX_SIZE_M = 12.0
_AREA_ENTITIES = frozenset({"HATCH", "MPOLYGON"})
_TEXT_ENTITIES = frozenset({"TEXT", "MTEXT", "ATTRIB"})
ANNOTATIONS = frozenset({"ATTDEF", "DIMENSION", "LEADER", "MULTILEADER", "VIEWPORT", "ACAD_TABLE"})
_GAP_EXAMPLES = 5
_SKIPPED = frozenset(
    {
        "ATTDEF",
        "DIMENSION",
        "LEADER",
        "MULTILEADER",
        "VIEWPORT",
        "IMAGE",
        "WIPEOUT",
        "OLE2FRAME",
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
        elif kind == "ACAD_PROXY_ENTITY" and getattr(entity, "proxy_graphic", None):
            outcome = self._proxy(entity, ref, layer, chain=chain, block=parent_block, owner=owner)
        elif kind == "REGION":
            outcome = self._region(entity, ref, layer, parent_block, owner)  # ty: ignore[invalid-argument-type]
        elif kind in _SKIPPED:
            self.skipped[kind] += 1
            outcome = f"skipped:{kind}:annotation"
            if kind not in ANNOTATIONS:
                reason = "unsupported-spatial-entity"
                if isinstance(entity, Body) and not entity.acis_data:
                    reason = "missing-acis-data"
                self._gap(kind, layer, parent_block, reason, ref)
                outcome = f"skipped:{kind}:{reason}"
        else:
            outcome = self._linework(entity, ref, layer, parent_block, owner)
        self.outcomes[outcome] += 1

    def _linework(
        self, entity: DXFGraphic, ref: SourceRef, layer: str, block: str | None, owner: str | None
    ) -> str:
        kind = entity.dxftype()
        try:
            geometry, error = self._geometry(entity)
        except HatchGeometryError as exc:
            return self._skip(kind, layer, block, str(exc), ref)
        if geometry is None or geometry.is_empty:
            return self._skip(kind, layer, block, "geometry-not-readable", ref)
        if not np.isfinite(shapely.get_coordinates(geometry)).all():
            return self._skip(kind, layer, block, "non-finite-coordinates", ref)
        if not geometry.is_valid:
            geometry = shapely.make_valid(geometry)
            error = None
        if error is None:
            self._gap(kind, layer, block, "approximation-error-not-bounded", ref)
        radius = abs(entity.dxf.radius) * self.unit_m if kind == "CIRCLE" else None
        center = entity.ocs().to_wcs(entity.dxf.center) if kind == "CIRCLE" else None
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
        return "feature"

    def _proxy(  # noqa: PLR0913 - как у вставки: слой, цепочка, блок и владелец-знак
        self,
        entity: DXFGraphic,
        ref: SourceRef,
        layer: str,
        *,
        chain: tuple[str, ...],
        block: str | None,
        owner: str | None,
    ) -> str:
        """Прокси-объект стороннего приложения читается по своему рисунку, как вставка:
        примитивы рисунка на слое «0» получают слой объекта. Документ не меняется."""
        try:
            children = list(entity.virtual_entities())  # ty: ignore[unresolved-attribute]
        except ValueError, TypeError, ArithmeticError, IndexError, struct.error:
            return self._skip("ACAD_PROXY_ENTITY", layer, block, "proxy-graphic-not-readable", ref)
        if not children:
            return self._skip("ACAD_PROXY_ENTITY", layer, block, "unsupported-spatial-entity", ref)
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
        return "proxy:graphic"

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

    def _insert(  # noqa: PLR0911 - один исход на каждый случай вставки
        self, insert: Insert, ref: SourceRef, layer: str, chain: tuple[str, ...], owner: str | None
    ) -> str:
        if insert.mcount > 1:
            for position, instance in enumerate(insert.multi_insert()):
                instance_ref = replace(ref, handle=f"{ref.handle}@{position}")
                self._insert(instance, instance_ref, layer, chain, owner)
            return "insert:multi"
        clip = XClip(insert)
        if clip.has_clipping_path and clip.is_clipping_enabled:
            # virtual_entities() ignores XCLIP. Using the full block could invent
            # positive soil evidence outside the visible crop. Until exact crop
            # semantics are supported, expose this gap instead of guessing.
            self.skipped["INSERT:XCLIP"] += 1
            self._gap("INSERT", layer, insert.dxf.name, "XCLIP-not-applied", ref)
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
        outcome, child_owner = self._role(insert, block, ref, layer, owner)
        if not self._explode(insert, ref, layer, (*chain, name), child_owner):
            self.skipped["INSERT:not-explodable"] += 1
            return "insert:not-explodable"
        return outcome

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
                points, error = polyline_vertices(entity, self.flatten)
                if isinstance(entity, Polyline) and entity.dxf.flags & 6:
                    error = None  # fit/spline-generated vertices need separate semantics
                return _polyline(points, closed=entity.is_closed), error
            if kind in _AREA_ENTITIES:
                return hatch_geometry(entity, self.flatten)  # ty: ignore[invalid-argument-type]
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
