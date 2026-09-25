"""Чтение DXF в доменную сцену: геометрия Shapely, исходный слой и ссылка на сущность."""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np
import shapely
from ezdxf.entities import Body, Circle, Ellipse, LWPolyline, MLine, MText, Polyline, Region, Text
from ezdxf.entities.boundary_paths import PolylinePath
from ezdxf.entities.image import Image, Wipeout
from ezdxf.entities.polygon import DXFPolygon
from ezdxf.lldxf.encoding import decode_dxf_unicode
from ezdxf.path import make_path
from ezdxf.tools.text import fast_plain_mtext, plain_text
from ezdxf.xclip import XClip
from shapely.geometry import LineString, Point, Polygon

from green.application.errors import InputError
from green.domain.objects import (
    NO_XREF,
    Feature,
    GeometryGap,
    InsertInstance,
    ReadDiagnostics,
    Scene,
    SourceRef,
    TextLabel,
)
from green.infrastructure.cad.acis_sidecar import load_region_sidecar
from green.infrastructure.cad.curve_paths import (
    circle_vertices,
    ellipse_vertices,
    polyline_vertices,
)
from green.infrastructure.cad.documents import load_document
from green.infrastructure.cad.hatch_footprint import bounded_hatch_footprint
from green.infrastructure.cad.hatch_geometry import (
    HatchGeometryError,
    associated_polyline_error,
    hatch_geometry,
    hatch_outline,
    linear_hatch_from_local_source,
    match_region_outline,
)
from green.infrastructure.cad.image_footprint import image_footprint
from green.infrastructure.cad.mline_footprint import bounded_mline_footprint
from green.infrastructure.cad.polyline_footprint import bounded_invalid_polyline
from green.infrastructure.cad.region_geometry import RegionGeometryError, region_polygon
from green.infrastructure.cad.units import AUTO, decide_units

if TYPE_CHECKING:
    from pathlib import Path

    from ezdxf.document import Drawing
    from ezdxf.entities import DXFGraphic, Insert
    from ezdxf.math import Matrix44
    from shapely.geometry.base import BaseGeometry

    from green.infrastructure.cad.documents import DocumentCache

MAX_BLOCK_DEPTH = 8
_AREA_ENTITIES = frozenset({"HATCH", "MPOLYGON"})
_TEXT_ENTITIES = frozenset({"TEXT", "MTEXT", "ATTRIB"})
_ANNOTATIONS = frozenset({"ATTDEF", "DIMENSION", "LEADER", "MULTILEADER", "VIEWPORT", "ACAD_TABLE"})
_GAP_EXAMPLES = 5
_MAX_HATCH_CLOSURE_M = 0.002
_ASSOCIATIVE_HATCH_MIN_AREA_RATIO = 0.5
_ASSOCIATIVE_HATCH_MAX_AREA_RATIO = 1.5
_DEGENERATE_LINE_ULPS = 64
_WIPEOUT_MIN_VERTICES = 4
_WIPEOUT_RECTANGLE_VERTICES = 2
_WIPEOUT_MAX_Z_SPAN = 1e-9
_SKIPPED = frozenset(
    {
        "ATTDEF",
        "DIMENSION",
        "LEADER",
        "MULTILEADER",
        "VIEWPORT",
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
        region_sat = load_region_sidecar(path, digest, doc)
        region_sat_by_sab: dict[bytes, tuple[str, ...]] = {}
        for handle, sat in region_sat.items():
            region = doc.entitydb.get(handle)
            if not isinstance(region, Region):
                raise InputError(f"ACIS sidecar: REGION {handle} исчез после чтения")
            sab_digest = hashlib.sha256(region.sab).digest()
            previous = region_sat_by_sab.get(sab_digest)
            if previous is not None and previous != sat:
                raise InputError("ACIS sidecar: одинаковые SAB дали разные SAT")
            region_sat_by_sab[sab_digest] = sat
        units = decide_units(doc, unit)
        # Обход идёт в единицах чертежа, поэтому метровые пороги делятся на размер единицы.
        walker = _Walker(
            doc=doc,
            file_sha8=digest[:8],
            flatten=self._flatten / units.unit_m,
            unit_m=units.unit_m,
            region_sat=region_sat,
            region_sat_by_sab=region_sat_by_sab,
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
            warnings=(
                *warnings,
                *units.notes,
                *((f"Восстановлен ACIS REGION: {len(region_sat)}",) if region_sat else ()),
                *walker.warnings(),
            ),
            unit_m=units.unit_m,
            read_diagnostics=ReadDiagnostics(
                visited_by_type=dict(walker.visited),
                skipped_by_type=dict(walker.skipped),
                bounded_uncertainty_by_type={
                    **(
                        {"HATCH": walker.bounded_unreadable_hatches}
                        if walker.bounded_unreadable_hatches
                        else {}
                    ),
                    **walker.bounded_invalid_polylines,
                    **({"MLINE": walker.bounded_mlines} if walker.bounded_mlines else {}),
                },
                unresolved_xrefs=tuple(sorted(walker.unresolved_xrefs)),
                geometry_gaps=walker.geometry_gaps(),
                approximation_features=sum(bool(f.geometry_error_m) for f in features),
                max_approximation_error_m=max(
                    (f.geometry_error_m or 0.0 for f in features), default=0.0
                ),
            ),
        )


@dataclass(slots=True)
class _Walker:
    doc: Drawing
    file_sha8: str
    flatten: float
    unit_m: float = 1.0
    region_sat: dict[str, tuple[str, ...]] = field(default_factory=dict)
    region_sat_by_sab: dict[bytes, tuple[str, ...]] = field(default_factory=dict)
    features: list[Feature] = field(default_factory=list)
    labels: list[TextLabel] = field(default_factory=list)
    skipped: Counter[str] = field(default_factory=Counter)
    visited: Counter[str] = field(default_factory=Counter)
    unresolved_xrefs: set[str] = field(default_factory=set)
    gaps: Counter[tuple[str, str, str | None, str]] = field(default_factory=Counter)
    gap_refs: dict[tuple[str, str, str | None, str], list[str]] = field(default_factory=dict)
    matched_region_hatches: int = 0
    matched_hatch_polylines: int = 0
    matched_local_hatches: int = 0
    collapsed_lines: int = 0
    bounded_unreadable_hatches: int = 0
    bounded_invalid_polylines: Counter[str] = field(default_factory=Counter)
    bounded_mlines: int = 0
    raster_footprints: int = 0

    def visit(  # noqa: C901, PLR0912, PLR0913, PLR0915 - entity dispatch with loss accounting
        self,
        entity: DXFGraphic,
        *,
        parent_layer: str | None,
        chain: tuple[str, ...],
        parent_handle: str,
        index: int,
        parent_block: str | None = None,
        insert_chain: tuple[InsertInstance, ...] = (),
        block_matrix: Matrix44 | None = None,
        sibling_regions: tuple[Region, ...] = (),
        sibling_hatches: tuple[DXFPolygon, ...] = (),
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
            self._label(entity, ref, layer, parent_block, chain)
        elif kind == "INSERT":
            self._insert(entity, ref, layer, chain, insert_chain)  # ty: ignore[invalid-argument-type]
        elif kind in _SKIPPED:
            self.skipped[kind] += 1
            if kind not in _ANNOTATIONS:
                reason = "unsupported-spatial-entity"
                if isinstance(entity, Body) and not entity.acis_data:
                    reason = "missing-acis-data"
                self._gap(kind, layer, parent_block, reason, ref)
        else:
            try:
                geometry, error = self._geometry(
                    entity,
                    block_matrix=block_matrix,
                    sibling_regions=sibling_regions,
                    sibling_hatches=sibling_hatches,
                )
            except (HatchGeometryError, RegionGeometryError) as exc:
                if (
                    isinstance(entity, DXFPolygon)
                    and kind == "HATCH"
                    and str(exc)
                    in {
                        "hatch-invalid-ring",
                        "hatch-open-boundary",
                        "hatch-intersecting-boundaries",
                        "hatch-disconnected-edges",
                    }
                ):
                    footprint = bounded_hatch_footprint(entity, self.flatten)
                    if footprint is not None:
                        self.features.append(
                            Feature(
                                ref=ref,
                                layer=layer,
                                geometry=footprint,
                                block=parent_block,
                                geometry_error_m=0.0,
                                source_entity_type=kind,
                                uncertain_footprint=True,
                                insert_chain=insert_chain,
                            )
                        )
                        self.bounded_unreadable_hatches += 1
                        return
                self.skipped[kind] += 1
                self._gap(kind, layer, parent_block, str(exc), ref)
                return
            if geometry is None or geometry.is_empty:
                self.skipped[kind] += 1
                self._gap(kind, layer, parent_block, "geometry-not-readable", ref)
            elif not np.isfinite(shapely.get_coordinates(geometry)).all():
                self.skipped[kind] += 1
                self._gap(kind, layer, parent_block, "non-finite-coordinates", ref)
            else:
                if kind == "MLINE":
                    self.features.append(
                        Feature(
                            ref=ref,
                            layer=layer,
                            geometry=geometry,
                            block=parent_block,
                            geometry_error_m=0.0,
                            source_entity_type=kind,
                            uncertain_footprint=True,
                            insert_chain=insert_chain,
                        )
                    )
                    self.bounded_mlines += 1
                    return
                if not geometry.is_valid:
                    if (
                        kind in {"LWPOLYLINE", "POLYLINE"}
                        and isinstance(geometry, Polygon)
                        and error is not None
                    ):
                        footprint = bounded_invalid_polyline(geometry, error, self.flatten)
                        if footprint is not None:
                            self.features.append(
                                Feature(
                                    ref=ref,
                                    layer=layer,
                                    geometry=footprint,
                                    block=parent_block,
                                    geometry_error_m=0.0,
                                    source_entity_type=kind,
                                    uncertain_footprint=True,
                                    insert_chain=insert_chain,
                                )
                            )
                            self.bounded_invalid_polylines[kind] += 1
                            return
                    geometry = shapely.make_valid(geometry)
                    error = None
                if error is None:
                    self._gap(kind, layer, parent_block, "approximation-error-not-bounded", ref)
                radius = abs(entity.dxf.radius) * self.unit_m if kind == "CIRCLE" else None
                center = entity.ocs().to_wcs(entity.dxf.center) if kind == "CIRCLE" else None
                self.features.append(
                    Feature(
                        ref=ref,
                        layer=layer,
                        geometry=geometry,
                        block=parent_block,
                        circle_radius_m=radius,
                        geometry_error_m=error * self.unit_m if error is not None else None,
                        source_entity_type=kind,
                        insert_chain=insert_chain,
                        circle_center_m=(center.x * self.unit_m, center.y * self.unit_m)
                        if center is not None
                        else None,
                    )
                )

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
        self,
        insert: Insert,
        ref: SourceRef,
        layer: str,
        chain: tuple[str, ...],
        insert_chain: tuple[InsertInstance, ...],
    ) -> None:
        if insert.mcount > 1:
            for position, instance in enumerate(insert.multi_insert()):
                instance_ref = replace(ref, handle=f"{ref.handle}@{position}")
                self._insert(instance, instance_ref, layer, chain, insert_chain)
            return
        clip = XClip(insert)
        if clip.has_clipping_path and clip.is_clipping_enabled:
            # virtual_entities() ignores XCLIP. Using the full block could invent
            # positive soil evidence outside the visible crop. Until exact crop
            # semantics are supported, expose this gap instead of guessing.
            self.skipped["INSERT:XCLIP"] += 1
            self._gap("INSERT", layer, insert.dxf.name, "XCLIP-not-applied", ref)
            return
        name = insert.dxf.name
        block = self.doc.blocks.get(name)
        if block is None or block.block is None:
            self.skipped["INSERT:no-block"] += 1
            return
        if (block.block.is_xref or block.block.is_xref_overlay) and len(block) == 0:
            self.unresolved_xrefs.add(name)
            return
        if len(chain) >= MAX_BLOCK_DEPTH:
            self.skipped["INSERT:too-deep"] += 1
            return
        position = insert.ocs().to_wcs(insert.dxf.insert)
        instances = (
            *insert_chain,
            InsertInstance(
                ref,
                decode_dxf_unicode(name),
                position.x,
                position.y,
                decode_dxf_unicode(insert.dxf.get("layer", "0")),
            ),
        )
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
                insert_chain=instances,
            )
        try:
            block_matrix = insert.matrix44()
            children = list(insert.virtual_entities(skipped_entity_callback=self._virtual_skip))
        except ValueError, TypeError, ArithmeticError:
            self.skipped["INSERT:not-explodable"] += 1
            return
        regions = tuple(child for child in children if isinstance(child, Region))
        hatches = tuple(
            child
            for child in children
            if isinstance(child, DXFPolygon) and child.dxftype() == "HATCH"
        )
        for position, child in enumerate(children):
            self.visit(
                child,
                parent_layer=layer,
                chain=(*chain, name),
                parent_handle=ref.handle,
                index=position,
                parent_block=name,
                insert_chain=instances,
                block_matrix=block_matrix,
                sibling_regions=regions,
                sibling_hatches=hatches,
            )

    def _virtual_skip(self, entity: DXFGraphic, reason: str) -> None:
        self.skipped[f"VIRTUAL:{entity.dxftype()}:{reason}"] += 1

    def _label(
        self,
        entity: DXFGraphic,
        ref: SourceRef,
        layer: str,
        block: str | None,
        chain: tuple[str, ...],
    ) -> None:
        # CIF escapes are not decoded by ezdxf on load, including R2007+.
        # Decode before stripping MTEXT control sequences, only in our scene;
        # keep the source Drawing unchanged for export and integrity checks.
        if isinstance(entity, MText):
            text = str(fast_plain_mtext(decode_dxf_unicode(entity.text)))
        else:
            text = plain_text(decode_dxf_unicode(entity.dxf.text))
        if not text or not text.strip():
            return
        original = entity.origin_of_copy or entity
        if (
            isinstance(original, Text)
            and (original.dxf.halign or original.dxf.valign)
            and not original.dxf.hasattr("align_point")
        ):
            # Text.transform() supplies a fallback before virtual_entities()
            # returns. Inspect the original too, or blocks hide missing data.
            self._gap(entity.dxftype(), layer, block, "text-alignment-point-missing", ref)
            self.skipped[entity.dxftype()] += 1
            return
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
            self._gap(entity.dxftype(), layer, block, "non-finite-text-coordinates", ref)
            self.skipped[entity.dxftype()] += 1
            return
        self.labels.append(
            TextLabel(
                ref=ref,
                layer=layer,
                x=point.x,
                y=point.y,
                text=text.strip(),
                block=block,
                block_chain=tuple(decode_dxf_unicode(name) for name in chain),
            )
        )

    def _geometry(  # noqa: C901, PLR0911, PLR0912 - one branch per entity type
        self,
        entity: DXFGraphic,
        *,
        block_matrix: Matrix44 | None = None,
        sibling_regions: tuple[Region, ...] = (),
        sibling_hatches: tuple[DXFPolygon, ...] = (),
    ) -> tuple[BaseGeometry | None, float | None]:
        kind = entity.dxftype()
        try:
            if isinstance(entity, Region):
                return region_polygon(
                    entity,
                    flatten=self.flatten,
                    block_matrix=block_matrix,
                    sat_lines=self._region_sat(entity),
                )
            if isinstance(entity, Wipeout):
                return _wipeout_geometry(entity)
            if isinstance(entity, Image):
                footprint = image_footprint(entity)
                if footprint is not None:
                    self.raster_footprints += 1
                return footprint, 0.0 if footprint is not None else None
            if isinstance(entity, MLine):
                footprint = bounded_mline_footprint(entity, self.flatten)
                return footprint, 0.0 if footprint is not None else None
            if kind == "LINE":
                start, end = entity.dxf.start, entity.dxf.end
                extent = max(abs(start.x), abs(start.y), abs(end.x), abs(end.y))
                length = math.hypot(start.x - end.x, start.y - end.y)
                if length <= _DEGENERATE_LINE_ULPS * math.ulp(extent):
                    self.collapsed_lines += 1
                    return Point(start.x, start.y), length
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
                    error = associated_polyline_error(
                        entity,
                        points,
                        error,
                        sibling_hatches,
                        self.flatten,
                        max_closure=_MAX_HATCH_CLOSURE_M / self.unit_m,
                        max_shift=0.02 / self.unit_m,
                    )
                    if error is not None:
                        self.matched_hatch_polylines += 1
                return _polyline(points, closed=entity.is_closed), error
            if kind in _AREA_ENTITIES:
                try:
                    return hatch_geometry(
                        entity,  # ty: ignore[invalid-argument-type]
                        self.flatten,
                        max_closure=_MAX_HATCH_CLOSURE_M / self.unit_m,
                    )
                except HatchGeometryError as error:
                    if str(error) == "hatch-intersecting-boundaries" and block_matrix is not None:
                        restored = linear_hatch_from_local_source(
                            entity,  # ty: ignore[invalid-argument-type]
                            block_matrix,
                            self.flatten,
                            max_closure=_MAX_HATCH_CLOSURE_M / self.unit_m,
                        )
                        if restored is not None:
                            self.matched_local_hatches += 1
                            return restored
                    if str(error) == "hatch-open-boundary":
                        return self._associated_region_hatch(entity, block_matrix)
                    if str(error) == "hatch-invalid-ring" and sibling_regions:
                        matched = self._matched_sibling_region_hatch(
                            entity, sibling_regions, block_matrix
                        )
                        if matched is not None:
                            self.matched_region_hatches += 1
                            return matched
                    raise
            path = make_path(entity)
            vertices = [(v.x, v.y) for v in path.flattening(self.flatten)]
        except HatchGeometryError, RegionGeometryError:
            raise
        except TypeError, ValueError, ArithmeticError, AttributeError:
            return None, None
        return _polyline(vertices, closed=path.is_closed), None if path.has_curves else 0.0

    def _matched_sibling_region_hatch(
        self,
        hatch: DXFGraphic,
        siblings: tuple[Region, ...],
        block_matrix: Matrix44 | None,
    ) -> tuple[Polygon, float] | None:
        """Infer a source only from one REGION in the same INSERT with matching boundary."""
        try:
            outline, error = hatch_outline(
                hatch,  # ty: ignore[invalid-argument-type]
                self.flatten,
                max_closure=_MAX_HATCH_CLOSURE_M / self.unit_m,
            )
        except HatchGeometryError:
            return None
        candidates = []
        for region in siblings:
            if decode_dxf_unicode(region.dxf.get("layer", "0")) != decode_dxf_unicode(
                hatch.dxf.get("layer", "0")
            ):
                continue
            try:
                candidates.append(
                    region_polygon(
                        region,
                        flatten=self.flatten,
                        block_matrix=block_matrix,
                        sat_lines=self._region_sat(region),
                    )
                )
            except RegionGeometryError:
                continue
        return match_region_outline(outline, error, candidates, max_shift=0.02 / self.unit_m)

    def _associated_region_hatch(
        self, hatch: DXFGraphic, block_matrix: Matrix44 | None
    ) -> tuple[BaseGeometry, float]:
        """Use a HATCH's explicit source REGION only when its vertices agree."""
        paths = hatch.paths.paths  # ty: ignore[unresolved-attribute]
        if not hatch.dxf.get("associative", 0) or len(paths) != 1:
            raise HatchGeometryError("hatch-open-boundary")
        path = paths[0]
        handles = path.source_boundary_objects
        if not isinstance(path, PolylinePath) or len(handles) != 1:
            raise HatchGeometryError("hatch-open-boundary")
        source = self.doc.entitydb.get(handles[0])
        if (
            not isinstance(source, Region)
            or source.dxf.get("owner") != hatch.dxf.get("owner")
            or source.dxf.get("layer", "0") != hatch.dxf.get("layer", "0")
        ):
            raise HatchGeometryError("hatch-open-boundary")
        local, error = region_polygon(
            source, flatten=self.flatten, sat_lines=self._region_sat(source)
        )
        if not path.vertices:
            raise HatchGeometryError("hatch-open-boundary")
        tolerance = max(error, 0.002 / self.unit_m)
        ocs = hatch.ocs()
        elevation = hatch.dxf.elevation.z
        points = [ocs.to_wcs((x, y, elevation)) for x, y, _ in path.vertices]
        if any(local.boundary.distance(Point(point.x, point.y)) > tolerance for point in points):
            raise HatchGeometryError("hatch-open-boundary")
        rough = Polygon([(point.x, point.y) for point in points])
        # A few associative paths self-intersect in their millimetre-sized
        # closure seam after DXF rounding. The REGION is the actual geometry;
        # this coarse area check only guards against an unrelated source link.
        if not (
            _ASSOCIATIVE_HATCH_MIN_AREA_RATIO
            <= rough.area / local.area
            <= _ASSOCIATIVE_HATCH_MAX_AREA_RATIO
        ):
            raise HatchGeometryError("hatch-open-boundary")
        if block_matrix is None:
            return local, error
        return region_polygon(
            source,
            flatten=self.flatten,
            block_matrix=block_matrix,
            sat_lines=self._region_sat(source),
        )

    def _region_sat(self, region: Region) -> tuple[str, ...] | None:
        handle = region.dxf.get("handle")
        if handle in self.region_sat:
            return self.region_sat[handle]
        if region.sab:
            return self.region_sat_by_sab.get(hashlib.sha256(region.sab).digest())
        return None

    def warnings(self) -> list[str]:  # noqa: C901 - one branch per import diagnostic
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
        if self.matched_region_hatches:
            messages.append(
                "HATCH восстановлены по единственному REGION того же блока и слоя: "
                f"{self.matched_region_hatches}"
            )
        if self.matched_hatch_polylines:
            messages.append(
                "Кривые POLYLINE сверены с исходной границей HATCH того же блока: "
                f"{self.matched_hatch_polylines}"
            )
        if self.matched_local_hatches:
            messages.append(
                "Прямые контуры HATCH объединены до преобразования блока: "
                f"{self.matched_local_hatches}"
            )
        if self.collapsed_lines:
            messages.append(
                "LINE с совпадающими в пределах округления концами представлены точкой: "
                f"{self.collapsed_lines}"
            )
        if self.bounded_unreadable_hatches:
            messages.append(
                "Повреждённые HATCH ограничены неопределённой областью без посадки: "
                f"{self.bounded_unreadable_hatches}"
            )
        if self.bounded_invalid_polylines:
            messages.append(
                "Самопересекающиеся POLYLINE/LWPOLYLINE ограничены неопределённой "
                f"областью без посадки: {sum(self.bounded_invalid_polylines.values())}"
            )
        if self.bounded_mlines:
            messages.append(
                f"MLINE ограничены неизвестной областью без посадки: {self.bounded_mlines}"
            )
        if self.raster_footprints:
            messages.append(
                "Рамки IMAGE прочитаны, содержимое растров не распознано: "
                f"{self.raster_footprints}. Уточните роль каждого изображения."
            )
        return messages


def _wipeout_geometry(entity: Wipeout) -> tuple[Polygon, float]:
    """Retain the exact display mask as unknown terrain, including INSERT transforms."""
    if entity.dxf.get("clip_mode", 0) != 0:
        raise HatchGeometryError("wipeout-unsupported-clip-mode")
    if (
        entity.dxf.get("clipping", 0) == 0
        and len(entity.boundary_path) != _WIPEOUT_RECTANGLE_VERTICES
    ):
        raise HatchGeometryError("wipeout-clipping-state-ambiguous")
    if not entity.boundary_path:
        raise HatchGeometryError("wipeout-invalid-boundary")
    vertices = entity.boundary_path_wcs()
    if len(vertices) < _WIPEOUT_MIN_VERTICES or not all(
        math.isfinite(value) for vertex in vertices for value in (vertex.x, vertex.y, vertex.z)
    ):
        raise HatchGeometryError("wipeout-invalid-boundary")
    z_span = max(vertex.z for vertex in vertices) - min(vertex.z for vertex in vertices)
    if z_span > _WIPEOUT_MAX_Z_SPAN:
        raise HatchGeometryError("wipeout-nonplanar-boundary")
    mask = Polygon((vertex.x, vertex.y) for vertex in vertices)
    if not mask.is_valid or mask.area <= 0:
        raise HatchGeometryError("wipeout-invalid-boundary")
    return mask, 0.0


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
            replace(
                feature,
                geometry=geometry,
                insert_chain=tuple(
                    replace(instance, x=instance.x * unit_m, y=instance.y * unit_m)
                    for instance in feature.insert_chain
                ),
            )
            for feature, geometry in zip(features, scaled, strict=True)
        ),
        tuple(replace(label, x=label.x * unit_m, y=label.y * unit_m) for label in labels),
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
