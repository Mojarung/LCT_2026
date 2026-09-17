"""Чтение DXF в доменную сцену: геометрия Shapely, исходный слой и ссылка на сущность."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from ezdxf import bbox
from ezdxf.addons import geo
from ezdxf.path import make_path
from shapely.geometry import LineString, Point, Polygon, shape

from green.domain.objects import NO_XREF, Feature, Scene, SourceRef, TextLabel
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.units import AUTO, decide_units

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.entities import DXFGraphic, Insert
    from ezdxf.layouts import BlockLayout
    from shapely.geometry.base import BaseGeometry

    from green.infrastructure.cad.documents import DocumentCache

SYMBOL_BLOCK_MAX_ENTITIES = 64
# Условный знак (люк, опора, дерево) умещается в квадрат 12 м; больше - это уже геометрия.
SYMBOL_MAX_SIZE_M = 12.0
# Экспорт из MicroStation (выгрузки Геотреста): каждый элемент - отдельный блок, это не символ.
# В привязанном (BIND) XREF имя блока получает префикс файла: "output[1-12]_...up$0$DIMTXT_3",
# у XREF без привязки разделитель "|". Проверка по началу имени такие блоки не видит.
ELEMENT_BLOCK = re.compile(r"(?:^|\$0\$|\|)msdElementType", re.IGNORECASE)
# Подпись сети Геотреста: текст и стрелка-выноска. Стрелка не должна стать трубой.
LABEL_BLOCK = re.compile(r"(?:^|\$0\$|\|)DIMTXT", re.IGNORECASE)
SMALL_CIRCLE_RADIUS_M = 2.0
MAX_BLOCK_DEPTH = 8
_AREA_ENTITIES = frozenset({"HATCH", "MPOLYGON"})
_TEXT_ENTITIES = frozenset({"TEXT", "MTEXT"})
_SKIPPED = frozenset(
    {
        "ATTDEF",
        "ATTRIB",
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
    unresolved_xrefs: set[str] = field(default_factory=set)
    block_sizes: dict[str, float] = field(default_factory=dict)

    def visit(  # noqa: PLR0913 - обход передаёт контекст родителя явно
        self,
        entity: DXFGraphic,
        *,
        parent_layer: str | None,
        chain: tuple[str, ...],
        parent_handle: str,
        index: int,
        labels_only: bool = False,
    ) -> None:
        layer = entity.dxf.get("layer", "0")
        if layer == "0" and parent_layer is not None:
            layer = parent_layer
        handle = entity.dxf.get("handle") or f"{parent_handle}~{index}"
        ref = SourceRef(self.file_sha8, _chain_hash(chain), handle)
        kind = entity.dxftype()

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
                    Feature(ref=ref, layer=layer, geometry=geometry, circle_radius_m=radius)
                )

    def _insert(self, insert: Insert, ref: SourceRef, layer: str, chain: tuple[str, ...]) -> None:
        name = insert.dxf.name
        block = self.doc.blocks.get(name)
        if block is None:
            self.skipped["INSERT:no-block"] += 1
            return
        if block.block_record.is_xref and len(block) == 0:
            self.unresolved_xrefs.add(name)
            return
        labels_only = LABEL_BLOCK.search(name) is not None
        if not labels_only and self._is_symbol(insert, block):
            point = insert.dxf.insert
            self.features.append(
                Feature(ref=ref, layer=layer, geometry=Point(point.x, point.y), block=name)
            )
            return
        if len(chain) >= MAX_BLOCK_DEPTH:
            self.skipped["INSERT:too-deep"] += 1
            return
        try:
            children = list(insert.virtual_entities())
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
            )

    def _is_symbol(self, insert: Insert, block: BlockLayout) -> bool:
        """Условный знак: маленький блок-не-xref, кроме элементов экспорта MicroStation."""
        name = block.name
        if (
            block.block_record.is_xref
            or len(block) > SYMBOL_BLOCK_MAX_ENTITIES
            or ELEMENT_BLOCK.search(name) is not None
        ):
            return False
        size = self.block_sizes.get(name)
        if size is None:
            extents = bbox.extents(_plain_entities(block, depth=0), fast=True)
            size = max(extents.size.x, extents.size.y) if extents.has_data else 0.0
            self.block_sizes[name] = size
        scale = max(abs(insert.dxf.get("xscale", 1.0)), abs(insert.dxf.get("yscale", 1.0)))
        return size * scale * self.unit_m <= SYMBOL_MAX_SIZE_M

    def _label(self, entity: DXFGraphic, ref: SourceRef, layer: str) -> None:
        text = entity.dxf.text if entity.dxftype() == "TEXT" else entity.plain_text()  # ty: ignore[unresolved-attribute]
        point = entity.dxf.insert
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
            if kind == "CIRCLE":
                center, radius = entity.dxf.center, entity.dxf.radius
                circle_center = Point(center.x, center.y)
                return (
                    circle_center
                    if radius * self.unit_m <= SMALL_CIRCLE_RADIUS_M
                    else circle_center.buffer(radius)
                )
            if kind == "LWPOLYLINE" and not entity.has_arc:  # ty: ignore[unresolved-attribute]
                points = [(x, y) for x, y in entity.get_points("xy")]  # ty: ignore[unresolved-attribute]
                return _polyline(points, closed=entity.closed)  # ty: ignore[unresolved-attribute]
            if kind in _AREA_ENTITIES:
                area = shape(geo.proxy(entity, distance=self.flatten))
                return area if area.is_valid else shapely.make_valid(area)
            vertices = [(v.x, v.y) for v in make_path(entity).flattening(self.flatten)]
        except TypeError, ValueError, ArithmeticError, AttributeError:
            return None
        return _polyline(vertices, closed=False)

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


def _plain_entities(entities: Iterable[DXFGraphic], *, depth: int) -> Iterator[DXFGraphic]:
    """Сущности блока для расчёта его размера, без побочных эффектов в документе.

    `bbox.extents` сам раскрывает вставки и отрисовывает выноски, а отрисовка MULTILEADER
    создаёт в документе блок стрелки: исходник получал сущность, которой в нём не было
    (docs/notes/22-source-document-untouched.md). Поэтому размеры, выноски и прочее из
    `_SKIPPED` сюда не попадают, а вставки раскрываются здесь же.
    """
    for entity in entities:
        kind = entity.dxftype()
        if kind in _SKIPPED:
            continue
        if kind != "INSERT":
            yield entity
        elif depth < MAX_BLOCK_DEPTH:
            try:
                children = list(entity.virtual_entities())  # ty: ignore[unresolved-attribute]
            except ValueError, TypeError, ArithmeticError:
                continue
            yield from _plain_entities(children, depth=depth + 1)


def _to_metres(
    features: list[Feature], labels: list[TextLabel], unit_m: float
) -> tuple[tuple[Feature, ...], tuple[TextLabel, ...]]:
    """Сцена в метрах: дальше по коду все пороги и нормы метровые."""
    if unit_m == 1.0 or not features:
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
