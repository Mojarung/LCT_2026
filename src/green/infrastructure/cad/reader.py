"""Чтение DXF в доменную сцену: геометрия Shapely, исходный слой и ссылка на сущность."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from ezdxf.addons import geo
from ezdxf.entities import Circle, LWPolyline
from ezdxf.path import make_path
from shapely.geometry import LineString, Point, Polygon, shape

from green.domain.objects import NO_XREF, Feature, ReadDiagnostics, Scene, SourceRef, TextLabel
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.units import AUTO, decide_units

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.entities import DXFGraphic, Insert
    from shapely.geometry.base import BaseGeometry

    from green.infrastructure.cad.documents import DocumentCache

# Подпись сети Геотреста: текст и стрелка-выноска. Стрелка не должна стать трубой.
LABEL_BLOCK = re.compile(r"(?:^|\$0\$|\|)DIMTXT", re.IGNORECASE)
MAX_BLOCK_DEPTH = 8
_AREA_ENTITIES = frozenset({"HATCH", "MPOLYGON"})
_TEXT_ENTITIES = frozenset({"TEXT", "MTEXT", "ATTRIB"})
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
        "REGION",
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
        features, labels = _to_metres(walker.features, walker.labels, units.unit_m)
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
            ),
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

    def visit(  # noqa: PLR0913 - обход передаёт контекст родителя явно
        self,
        entity: DXFGraphic,
        *,
        parent_layer: str | None,
        chain: tuple[str, ...],
        parent_handle: str,
        index: int,
        labels_only: bool = False,
        parent_block: str | None = None,
    ) -> None:
        layer = entity.dxf.get("layer", "0")
        if layer == "0" and parent_layer is not None:
            layer = parent_layer
        handle = entity.dxf.get("handle") or f"{parent_handle}~{index}"
        ref = SourceRef(self.file_sha8, _chain_hash(chain), handle)
        kind = entity.dxftype()
        self.visited[kind] += 1

        if kind in _TEXT_ENTITIES:
            self._label(entity, ref, layer)
        elif labels_only:
            self.skipped[f"{kind}:label-leader"] += 1
        elif kind == "INSERT":
            self._insert(entity, ref, layer, chain)  # ty: ignore[invalid-argument-type]
        elif kind in _SKIPPED:
            self.skipped[kind] += 1
        else:
            geometry = self._geometry(entity)
            if geometry is None or geometry.is_empty:
                self.skipped[kind] += 1
            else:
                radius = entity.dxf.radius * self.unit_m if kind == "CIRCLE" else None
                self.features.append(
                    Feature(
                        ref=ref,
                        layer=layer,
                        geometry=geometry,
                        block=parent_block,
                        circle_radius_m=radius,
                    )
                )

    def _insert(self, insert: Insert, ref: SourceRef, layer: str, chain: tuple[str, ...]) -> None:
        if insert.mcount > 1:
            for position, instance in enumerate(insert.multi_insert()):
                instance_ref = replace(ref, handle=f"{ref.handle}@{position}")
                self._insert(instance, instance_ref, layer, chain)
            return
        name = insert.dxf.name
        block = self.doc.blocks.get(name)
        if block is None or block.block is None:
            self.skipped["INSERT:no-block"] += 1
            return
        if (block.block.is_xref or block.block.is_xref_overlay) and len(block) == 0:
            self.unresolved_xrefs.add(name)
            return
        labels_only = LABEL_BLOCK.search(name) is not None
        if len(chain) >= MAX_BLOCK_DEPTH:
            self.skipped["INSERT:too-deep"] += 1
            return
        for position, attribute in enumerate(insert.attribs):
            # Attached values are instance data, not the ATTDEF default. Copying
            # removes the handle so MINSERT instances get distinct source refs.
            self.visit(
                attribute.copy(),
                parent_layer=layer,
                chain=(*chain, name),
                parent_handle=f"{ref.handle}/attrib",
                index=position,
                parent_block=name,
            )
        try:
            children = list(insert.virtual_entities(skipped_entity_callback=self._virtual_skip))
        except ValueError, TypeError, ArithmeticError:
            self.skipped["INSERT:not-explodable"] += 1
            return
        for position, child in enumerate(children):
            self.visit(
                child,
                parent_layer=layer,
                chain=(*chain, name),
                parent_handle=ref.handle,
                index=position,
                labels_only=labels_only,
                parent_block=name,
            )

    def _virtual_skip(self, entity: DXFGraphic, reason: str) -> None:
        self.skipped[f"VIRTUAL:{entity.dxftype()}:{reason}"] += 1

    def _label(self, entity: DXFGraphic, ref: SourceRef, layer: str) -> None:
        is_mtext = entity.dxftype() == "MTEXT"
        text = entity.plain_text() if is_mtext else entity.dxf.text  # ty: ignore[unresolved-attribute]
        point = entity.dxf.insert
        if not is_mtext:
            point = entity.ocs().to_wcs(point)
        if text and text.strip():
            self.labels.append(
                TextLabel(ref=ref, layer=layer, x=point.x, y=point.y, text=text.strip())
            )

    def _geometry(self, entity: DXFGraphic) -> BaseGeometry | None:  # noqa: PLR0911 - one branch per entity type
        kind = entity.dxftype()
        try:
            if kind == "LINE":
                start, end = entity.dxf.start, entity.dxf.end
                return LineString([(start.x, start.y), (end.x, end.y)])
            if kind == "POINT":
                location = entity.dxf.location
                return Point(location.x, location.y)
            if isinstance(entity, Circle):
                tolerance = min(self.flatten, entity.dxf.radius / 64)
                points = [(v.x, v.y) for v in entity.flattening(tolerance)]
                return _polyline(points, closed=True)
            if isinstance(entity, LWPolyline) and not entity.has_arc:
                points = [(v.x, v.y) for v in entity.vertices_in_wcs()]
                return _polyline(points, closed=entity.closed)
            if kind in _AREA_ENTITIES:
                area = shape(geo.proxy(entity, distance=self.flatten))
                return area if area.is_valid else shapely.make_valid(area)
            path = make_path(entity)
            vertices = [(v.x, v.y) for v in path.flattening(self.flatten)]
        except TypeError, ValueError, ArithmeticError, AttributeError:
            return None
        return _polyline(vertices, closed=path.is_closed)

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
    features: list[Feature], labels: list[TextLabel], unit_m: float
) -> tuple[tuple[Feature, ...], tuple[TextLabel, ...]]:
    """Сцена в метрах: дальше по коду все пороги и нормы метровые."""
    if unit_m == 1.0:
        return tuple(features), tuple(labels)
    scaled = shapely.transform(
        np.asarray([f.geometry for f in features], dtype=object), lambda xy: xy * unit_m
    )
    return (
        tuple(
            replace(feature, geometry=geometry)
            for feature, geometry in zip(features, scaled, strict=True)
        ),
        tuple(replace(label, x=label.x * unit_m, y=label.y * unit_m) for label in labels),
    )


def _polyline(points: list[tuple[float, float]], *, closed: bool) -> BaseGeometry | None:
    unique = list(dict.fromkeys(points))
    if closed and len(unique) >= 3:  # noqa: PLR2004 - polygon needs three vertices
        polygon = Polygon(points)
        return polygon if polygon.is_valid else shapely.make_valid(polygon)
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
