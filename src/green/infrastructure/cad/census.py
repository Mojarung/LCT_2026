"""Перепись вставок-знаков своим обходом: второй счёт того, что ридер отдаёт экземплярами.

Ридер находит знаки по ходу общего разбора (virtual_entities, штрих за штрихом); перепись
обходит только вставки, матрицами, не разбирая рисунок. Критерий контейнера общий (обёртка
MicroStation, DIMTXT, анонимный блок, больше 64 примитивов, больше 12 м): иначе счёты не
сравнимы. Совпадение двух счётов - доказательство, что знак не потерялся и не удвоился.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import shapely
from ezdxf import bbox
from ezdxf.entities import Insert
from ezdxf.lldxf.encoding import decode_dxf_unicode
from ezdxf.math import BoundingBox2d, Matrix44
from ezdxf.xclip import XClip
from shapely.geometry import Point, Polygon

from green.application.semantic_names import base_name, local_name
from green.infrastructure.cad.reader import (
    ANNOTATIONS,
    CONTAINER_PREFIXES,
    MAX_BLOCK_DEPTH,
    SYMBOL_MAX_PRIMITIVES,
    SYMBOL_MAX_SIZE_M,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ezdxf.document import Drawing
    from ezdxf.entities import DXFGraphic
    from ezdxf.layouts import BlockLayout
    from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True, slots=True)
class InsertRecord:
    """Экземпляр знака: блок, код знака, слой, точка вставки в метрах, глубина вложенности."""

    block: str
    base: str
    layer: str
    x: float
    y: float
    depth: int


def _clip_region(clip: XClip, matrix: Matrix44) -> BaseGeometry | None:
    """Видимая область обычной обрезки в мировых координатах: путь блока через полную
    матрицу (у вложенной вставки собственная matrix44 - координаты родительского блока)."""
    path = clip.get_block_clipping_path()
    if clip.is_inverted_clip or path.is_inverted_clip:
        return None
    vertices = list(path.vertices)
    if len(vertices) == 2:  # noqa: PLR2004 - прямоугольник по двум углам
        vertices = list(BoundingBox2d(vertices).rect_vertices())
    if len(vertices) < 3:  # noqa: PLR2004 - многоугольник
        return None
    world = [(v.x, v.y) for v in matrix.transform_vertices(vertices)]
    area = shapely.make_valid(Polygon(world))
    return area if area.area > 0 else None


def insert_census(doc: Drawing, *, unit_m: float) -> list[InsertRecord]:
    census = _Census(doc, unit_m)
    census.walk(doc.modelspace(), Matrix44(), None, (), ())
    return census.records


class _Census:
    def __init__(self, doc: Drawing, unit_m: float) -> None:
        self.doc = doc
        self.unit_m = unit_m
        self.records: list[InsertRecord] = []
        self.sizes: dict[str, bbox.BoundingBox | None] = {}

    def walk(
        self,
        entities: Iterable[DXFGraphic],
        matrix: Matrix44,
        parent_layer: str | None,
        chain: tuple[str, ...],
        clips: tuple[BaseGeometry, ...],
    ) -> None:
        for entity in entities:
            if isinstance(entity, Insert):
                layer = decode_dxf_unicode(entity.dxf.get("layer", "0"))
                if layer == "0" and parent_layer is not None:
                    layer = parent_layer
                instances = entity.multi_insert() if entity.mcount > 1 else [entity]
                for instance in instances:
                    self._insert(instance, matrix, layer, chain, clips)

    def _insert(
        self,
        insert: Insert,
        matrix: Matrix44,
        layer: str,
        chain: tuple[str, ...],
        clips: tuple[BaseGeometry, ...],
    ) -> None:
        clip = XClip(insert)
        if clip.has_clipping_path and clip.is_clipping_enabled:
            region = _clip_region(clip, insert.matrix44() @ matrix)
            if region is None:
                return  # инвертированная обрезка: ридер тоже пропускает вставку
            clips = (*clips, region)
        name = insert.dxf.name
        block = self.doc.blocks.get(name)
        if block is None or block.block is None or len(chain) >= MAX_BLOCK_DEPTH:
            return
        if (block.block.is_xref or block.block.is_xref_overlay) and len(block) == 0:
            return
        total = insert.matrix44() @ matrix
        if self._container(block, total):
            self.walk(block, total, layer, (*chain, name), clips)
            return
        point = total.transform(block.block.dxf.get("base_point", (0, 0, 0)))
        if not all(region.covers(Point(point.x, point.y)) for region in clips):
            return  # знак за рамкой обрезки: на плане его нет
        decoded = decode_dxf_unicode(name)
        self.records.append(
            InsertRecord(
                block=decoded,
                base=base_name(decoded),
                layer=layer,
                x=point.x * self.unit_m,
                y=point.y * self.unit_m,
                depth=len(chain),
            )
        )

    def _container(self, block: BlockLayout, matrix: Matrix44) -> bool:
        if local_name(decode_dxf_unicode(block.name)).casefold().startswith(CONTAINER_PREFIXES):
            return True
        if len(block) > SYMBOL_MAX_PRIMITIVES:
            return True
        box = self._box(block, 0)
        if box is None or not box.has_data:
            return True
        scale = max(matrix.ux.magnitude, matrix.uy.magnitude)
        return max(box.size.x, box.size.y) * scale * self.unit_m > SYMBOL_MAX_SIZE_M

    def _box(self, block: BlockLayout, depth: int) -> bbox.BoundingBox | None:
        """Габарит рисунка блока в его единицах; аннотации не разбираются (чтение не меняет
        документ), вложенные вставки - углами своего габарита через матрицу."""
        if block.name in self.sizes:
            return self.sizes[block.name]
        self.sizes[block.name] = None
        box = bbox.BoundingBox()
        for entity in block:
            if entity.dxftype() in ANNOTATIONS:
                continue
            if not isinstance(entity, Insert):
                box.extend(bbox.extents([entity], fast=True))
                continue
            inner = self.doc.blocks.get(entity.dxf.name)
            inner_box = (
                None if inner is None or depth >= MAX_BLOCK_DEPTH else self._box(inner, depth + 1)
            )
            if inner_box is None or not inner_box.has_data:
                continue
            (x0, y0, _), (x1, y1, _) = inner_box.extmin, inner_box.extmax
            corners = [(x0, y0, 0), (x1, y0, 0), (x1, y1, 0), (x0, y1, 0)]
            for instance in entity.multi_insert() if entity.mcount > 1 else [entity]:
                box.extend(instance.matrix44().transform_vertices(corners))
        self.sizes[block.name] = box if box.has_data else None
        return self.sizes[block.name]
