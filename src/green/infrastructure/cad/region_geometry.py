"""Decode only a REGION whose entire ACIS body is one flat straight-edged face."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import numpy as np
from ezdxf.acis import api
from shapely.geometry import Polygon

if TYPE_CHECKING:
    from ezdxf.entities import Region
    from ezdxf.math import Matrix44

_SINGLETONS = ("body", "lump", "shell", "face", "loop", "plane-surface")
_PER_EDGE = ("coedge", "edge", "vertex", "point", "straight-curve")
_ALLOWED = frozenset((*_SINGLETONS, *_PER_EDGE, "transform"))
_MIN_EDGES = 3
_MAX_EDGES = 10_000


class RegionGeometryError(ValueError):
    """The complete planar contour cannot be established from this ACIS body."""


def simple_region_polygon(region: Region, *, block_matrix: Matrix44 | None = None) -> Polygon:
    if not region.sat and not region.sab:
        raise RegionGeometryError("missing-acis-data")
    try:
        bodies = api.load_dxf(region)
        if len(bodies) != 1:
            raise RegionGeometryError("acis-body-count-unsupported")
        body = bodies[0]
        edges = _validated_edge_count(body)
        polygon = _polygon_from_body(body, edges, block_matrix)
    except (api.AcisException, AttributeError, IndexError, KeyError, TypeError) as exc:
        raise RegionGeometryError("acis-parse-error") from exc
    else:
        return polygon


def _validated_edge_count(body: api.Body) -> int:
    counts = Counter(node.type for node in api.AcisDebugger(body).walk())
    if counts.keys() - _ALLOWED:
        raise RegionGeometryError("acis-entity-unsupported")
    if any(counts[kind] != 1 for kind in _SINGLETONS) or counts["transform"] > 1:
        raise RegionGeometryError("acis-topology-unsupported")
    edges = counts["edge"]
    if not _MIN_EDGES <= edges <= _MAX_EDGES or any(
        counts[kind] != edges for kind in _PER_EDGE
    ):
        raise RegionGeometryError("acis-edge-unsupported")
    if not _closed_straight_loop(body, edges):
        raise RegionGeometryError("acis-loop-open-or-ambiguous")
    return edges


def _closed_straight_loop(body: api.Body, edges: int) -> bool:
    first = body.lump.shell.face.loop.coedge
    if first.is_none:
        return False
    coedge = first
    visited: set[int] = set()
    vertices = []
    for _ in range(edges):
        if coedge.is_none or id(coedge) in visited:
            return False
        visited.add(id(coedge))
        edge = coedge.edge
        if edge.is_none or edge.curve.type != "straight-curve":
            return False
        start, end = edge.start_vertex, edge.end_vertex
        if start.is_none or end.is_none:
            return False
        vertices.append((end, start) if coedge.sense else (start, end))
        coedge = coedge.next_coedge
    if coedge is not first:
        return False
    return all(vertices[index][1] is vertices[(index + 1) % edges][0] for index in range(edges))


def _polygon_from_body(body: api.Body, edges: int, block_matrix: Matrix44 | None) -> Polygon:
    meshes = api.mesh_from_body(body)
    if len(meshes) != 1 or len(meshes[0].faces) != 1:
        raise RegionGeometryError("acis-mesh-incomplete")
    mesh = meshes[0]
    face = mesh.faces[0]
    if len(face) != edges or len(mesh.vertices) != edges or len(set(face)) != edges:
        raise RegionGeometryError("acis-mesh-incomplete")
    vertices = [mesh.vertices[index] for index in face]
    if block_matrix is not None:
        vertices = list(block_matrix.transform_vertices(vertices))
    coordinates = np.array(vertices, dtype=float)
    if not np.isfinite(coordinates).all():
        raise RegionGeometryError("non-finite-coordinates")
    if not np.allclose(coordinates[:, 2], coordinates[0, 2], rtol=0, atol=1e-9):
        raise RegionGeometryError("acis-face-not-horizontal")
    polygon = Polygon(coordinates[:, :2])
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 0:
        raise RegionGeometryError("acis-polygon-invalid")
    return polygon
