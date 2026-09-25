"""Read a single planar ACIS REGION, including bounded SAT elliptical arcs."""

from __future__ import annotations

import math
from collections import Counter
from typing import TYPE_CHECKING

import numpy as np
from ezdxf.acis import api
from ezdxf.acis.entities import SatLoader
from ezdxf.acis.sat import SatEntity
from ezdxf.math import Vec3
from shapely.geometry import Polygon

from green.infrastructure.cad.polygon_repair import repair_roundoff_self_intersection

if TYPE_CHECKING:
    from ezdxf.acis.entities import Body
    from ezdxf.entities import Region
    from ezdxf.math import Matrix44

_SINGLETONS = ("body", "lump", "shell", "face", "loop", "plane-surface")
_PER_EDGE = ("coedge", "edge", "vertex", "point")
_ALLOWED = frozenset(
    (*_SINGLETONS, *_PER_EDGE, "straight-curve", "unsupported-entity", "transform")
)
_MIN_STRAIGHT_EDGES = 3
_MIN_CURVED_EDGES = 2
_MAX_EDGES = 10_000
_MAX_VERTICES = 100_000
_ENDPOINT_TOLERANCE = 1e-6
_MIN_AXIS = 1e-12
_MIN_RATIO = 1e-6
_NAMED_ATTRIBUTE_FIELDS = 7
_NAMED_INT_ATTRIBUTE = "named_int_attribute-named_attribute-st-attrib"


class RegionGeometryError(ValueError):
    """The complete planar contour cannot be established from this ACIS body."""


def region_polygon(
    region: Region,
    *,
    flatten: float,
    block_matrix: Matrix44 | None = None,
    sat_lines: tuple[str, ...] | None = None,
) -> tuple[Polygon, float]:
    """Return a footprint and an upper bound on curve sampling error in DXF units."""
    sat_data = sat_lines if sat_lines is not None else region.sat
    if not sat_data and not region.sab:
        raise RegionGeometryError("missing-acis-data")
    try:
        loader = SatLoader(sat_data) if sat_data else None
        if loader is None:
            bodies = api.load_dxf(region)
        else:
            loader.load_entities()
            bodies = loader.bodies()
        if len(bodies) != 1:
            raise RegionGeometryError("acis-body-count-unsupported")
        body = bodies[0]
        metadata = _named_attribute_ids(loader) if loader is not None else set()
        edges, curved, reachable = _validated_edge_count(body, metadata)
        if loader is not None:
            detached = [
                record
                for record in loader.records
                if id(loader.entities[id(record)]) not in reachable | metadata
            ]
            if len(detached) > 1 or any(record.name != "asmheader" for record in detached):
                raise RegionGeometryError("acis-detached-entities")
        if curved:
            if loader is None:
                raise RegionGeometryError("acis-curved-sab-unsupported")
            raw = {
                id(loader.entities[id(record)]): record
                for record in loader.records
                if isinstance(record, SatEntity)
            }
            if len(raw) != len(loader.records):
                raise RegionGeometryError("acis-record-type-unsupported")
            return _curved_polygon(body, edges, raw, flatten, block_matrix)
        return _straight_polygon(body, edges, block_matrix), 0.0
    except (api.AcisException, AttributeError, IndexError, KeyError, TypeError) as exc:
        raise RegionGeometryError("acis-parse-error") from exc


def _named_attribute_ids(loader: SatLoader) -> set[int]:
    """Recognize non-geometric, length-checked SAT named attributes only."""
    return {
        id(loader.entities[id(record)])
        for record in loader.records
        if isinstance(record, SatEntity) and _is_named_metadata(record)
    }


def _is_named_metadata(record: SatEntity) -> bool:
    if record.name != _NAMED_INT_ATTRIBUTE or len(record.data) != _NAMED_ATTRIBUTE_FIELDS:
        return False
    previous, following, owner, name_marker, name, value_marker, value = record.data
    if not all(isinstance(pointer, SatEntity) for pointer in (previous, following, owner)):
        return False
    if owner.name not in {"body", "lump", "shell", "face"} or any(
        pointer.name not in {"null-ptr", _NAMED_INT_ATTRIBUTE} for pointer in (previous, following)
    ):
        return False
    return all(isinstance(item, str) for item in (name_marker, name, value_marker, value)) and (
        _is_length_prefixed(name_marker, name) and _is_length_prefixed(value_marker, value)
    )


def _is_length_prefixed(marker: str, value: str) -> bool:
    return marker.startswith("@") and marker[1:].isdigit() and int(marker[1:]) == len(value)


def _validated_edge_count(body: Body, metadata: set[int]) -> tuple[int, bool, set[int]]:
    nodes = tuple(node for node in api.AcisDebugger(body).walk() if id(node) not in metadata)
    counts = Counter(node.type for node in nodes)
    if counts.keys() - _ALLOWED:
        raise RegionGeometryError("acis-entity-unsupported")
    if any(counts[kind] != 1 for kind in _SINGLETONS) or counts["transform"] > 1:
        raise RegionGeometryError("acis-topology-unsupported")
    edges = counts["edge"]
    curved = bool(counts["unsupported-entity"])
    minimum = _MIN_CURVED_EDGES if curved else _MIN_STRAIGHT_EDGES
    if not minimum <= edges <= _MAX_EDGES or any(counts[kind] != edges for kind in _PER_EDGE):
        raise RegionGeometryError("acis-edge-unsupported")
    if counts["straight-curve"] + counts["unsupported-entity"] != edges:
        raise RegionGeometryError("acis-curve-count-unsupported")
    if not _closed_loop(body, edges, curved=curved):
        raise RegionGeometryError("acis-loop-open-or-ambiguous")
    return edges, curved, {id(node) for node in nodes}


def _closed_loop(body: Body, edges: int, *, curved: bool) -> bool:
    loop = body.lump.shell.face.loop
    first = loop.coedge
    if first.is_none:
        return False
    coedge = first
    visited: set[int] = set()
    vertices = []
    allowed = ("straight-curve", "unsupported-entity") if curved else ("straight-curve",)
    for _ in range(edges):
        if coedge.is_none or id(coedge) in visited:
            return False
        visited.add(id(coedge))
        edge = coedge.edge
        if (
            edge.is_none
            or edge.curve.type not in allowed
            or coedge.loop is not loop
            or coedge.next_coedge.prev_coedge is not coedge
            or not coedge.partner_coedge.is_none
            or edge.coedge is not coedge
        ):
            return False
        start, end = edge.start_vertex, edge.end_vertex
        if start.is_none or end.is_none:
            return False
        vertices.append((end, start) if coedge.sense else (start, end))
        coedge = coedge.next_coedge
    if coedge is not first:
        return False
    return all(vertices[index][1] is vertices[(index + 1) % edges][0] for index in range(edges))


def _straight_polygon(body: Body, edges: int, block_matrix: Matrix44 | None) -> Polygon:
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
    return _checked_polygon(vertices)


def _curved_polygon(
    body: Body,
    edges: int,
    raw: dict[int, SatEntity],
    flatten: float,
    block_matrix: Matrix44 | None,
) -> tuple[Polygon, float]:
    body_matrix = None if body.transform.is_none else body.transform.matrix
    first = body.lump.shell.face.loop.coedge
    coedge = first
    vertices: list[Vec3] = []
    error = 0.0
    for _ in range(edges):
        edge = coedge.edge
        start, end = (
            (edge.end_vertex.point.location, edge.start_vertex.point.location)
            if coedge.sense
            else (edge.start_vertex.point.location, edge.end_vertex.point.location)
        )
        if not vertices:
            vertices.append(_transform(start, body_matrix, block_matrix))
        if edge.curve.type == "straight-curve":
            vertices.append(_transform(end, body_matrix, block_matrix))
        else:
            record = raw.get(id(edge.curve))
            if record is None or record.name != "ellipse-curve":
                raise RegionGeometryError("acis-curve-unsupported")
            samples, bound = _sample_ellipse(
                record,
                start,
                end,
                reversed_sense=edge.sense != coedge.sense,
                flatten=flatten,
                body_matrix=body_matrix,
                block_matrix=block_matrix,
            )
            vertices.extend(samples)
            error = max(error, bound)
        if len(vertices) > _MAX_VERTICES:
            raise RegionGeometryError("acis-vertex-budget-exceeded")
        coedge = coedge.next_coedge
    if coedge is not first:
        raise RegionGeometryError("acis-loop-open-or-ambiguous")
    closure_error = vertices[0].distance(vertices[-1])
    if closure_error > _ENDPOINT_TOLERANCE:
        raise RegionGeometryError("acis-loop-disconnected")
    return _checked_polygon(vertices[:-1]), max(error, closure_error)


def _sample_ellipse(  # noqa: C901, PLR0912, PLR0913, PLR0915 - validate SAT explicitly
    record: SatEntity,
    start: Vec3,
    end: Vec3,
    *,
    reversed_sense: bool,
    flatten: float,
    body_matrix: Matrix44 | None,
    block_matrix: Matrix44 | None,
) -> tuple[list[Vec3], float]:
    tokens = record.data
    if tokens and hasattr(tokens[0], "is_null_ptr"):
        if not tokens[0].is_null_ptr:
            raise RegionGeometryError("acis-curve-pattern-unsupported")
        tokens = tokens[1:]
    if len(tokens) != 12 or tokens[10:] != ["I", "I"]:  # noqa: PLR2004 - SAT contract
        raise RegionGeometryError("acis-curve-bounds-unsupported")
    try:
        values = np.array([float(token) for token in tokens[:10]], dtype=float)
    except ValueError as exc:
        raise RegionGeometryError("acis-curve-parameters-invalid") from exc
    if not np.isfinite(values).all():
        raise RegionGeometryError("acis-curve-parameters-invalid")
    center = values[:3]
    normal = values[3:6]
    major = values[6:9]
    ratio = values[9]
    radius = math.hypot(*major)
    if (
        not _MIN_RATIO <= ratio <= 1
        or not math.isfinite(radius)
        or radius < _MIN_AXIS
        or not math.isclose(float(np.linalg.norm(normal)), 1.0, abs_tol=1e-6)
        or abs(float(np.dot(normal, major))) > 1e-6 * radius
    ):
        raise RegionGeometryError("acis-curve-parameters-invalid")
    minor = np.cross(normal, major) * ratio
    angles = []
    residual = 0.0
    for vertex in (start, end):
        point = np.asarray(vertex, dtype=float)
        delta = point - center
        cosine = float(np.dot(delta, major) / np.dot(major, major))
        sine = float(np.dot(delta, minor) / np.dot(minor, minor))
        angle = math.atan2(sine, cosine)
        fitted = center + major * math.cos(angle) + minor * math.sin(angle)
        deviation = float(np.linalg.norm(fitted - point))
        if not math.isfinite(deviation):
            raise RegionGeometryError("acis-curve-parameters-invalid")
        residual = max(residual, deviation)
        angles.append(angle)
    if residual > max(_ENDPOINT_TOLERANCE, radius * 1e-8):
        raise RegionGeometryError("acis-curve-endpoints-off-ellipse")
    sign = -1 if reversed_sense else 1
    sweep = ((angles[1] - angles[0]) * sign) % math.tau
    if not 0 < sweep < math.tau - 1e-12:
        raise RegionGeometryError("acis-curve-sweep-ambiguous")
    major_world = _transform_direction(Vec3(major), body_matrix, block_matrix)
    minor_world = _transform_direction(Vec3(minor), body_matrix, block_matrix)
    axis_bound = math.hypot(major_world.magnitude, minor_world.magnitude)
    if not math.isfinite(axis_bound) or axis_bound <= 0:
        raise RegionGeometryError("acis-curve-parameters-invalid")
    tolerance = min(flatten, axis_bound / 128)
    if tolerance <= 0:
        raise RegionGeometryError("acis-curve-tolerance-invalid")
    estimated_count = sweep * math.sqrt(axis_bound / (8 * tolerance))
    if not math.isfinite(estimated_count) or estimated_count > _MAX_VERTICES:
        raise RegionGeometryError("acis-vertex-budget-exceeded")
    count = max(2, math.ceil(estimated_count))
    samples = [
        _transform(
            Vec3(
                center
                + major * math.cos(angles[0] + sign * sweep * index / count)
                + minor * math.sin(angles[0] + sign * sweep * index / count)
            ),
            body_matrix,
            block_matrix,
        )
        for index in range(1, count)
    ]
    samples.append(_transform(end, body_matrix, block_matrix))
    endpoint_bound = residual * _linear_scale_bound(body_matrix, block_matrix)
    return samples, axis_bound * sweep * sweep / (8 * count * count) + endpoint_bound


def _transform(point: Vec3, body_matrix: Matrix44 | None, block_matrix: Matrix44 | None) -> Vec3:
    if body_matrix is not None:
        point = body_matrix.transform(point)
    if block_matrix is not None:
        point = block_matrix.transform(point)
    return point


def _transform_direction(
    direction: Vec3, body_matrix: Matrix44 | None, block_matrix: Matrix44 | None
) -> Vec3:
    if body_matrix is not None:
        direction = body_matrix.transform_direction(direction)
    if block_matrix is not None:
        direction = block_matrix.transform_direction(direction)
    return direction


def _linear_scale_bound(body_matrix: Matrix44 | None, block_matrix: Matrix44 | None) -> float:
    """Frobenius norm bounds the length of any transformed residual vector."""
    if body_matrix is None and block_matrix is None:
        return 1.0
    basis = (Vec3(1, 0, 0), Vec3(0, 1, 0), Vec3(0, 0, 1))
    scale = math.sqrt(
        sum(_transform_direction(axis, body_matrix, block_matrix).magnitude ** 2 for axis in basis)
    )
    if not math.isfinite(scale):
        raise RegionGeometryError("acis-transform-invalid")
    return scale


def _checked_polygon(vertices: list[Vec3]) -> Polygon:
    coordinates = np.array(vertices, dtype=float)
    if not np.isfinite(coordinates).all():
        raise RegionGeometryError("non-finite-coordinates")
    if not np.allclose(coordinates[:, 2], coordinates[0, 2], rtol=0, atol=1e-9):
        raise RegionGeometryError("acis-face-not-horizontal")
    polygon = Polygon(coordinates[:, :2])
    if polygon.is_empty or not math.isfinite(polygon.area) or polygon.area <= 0:
        raise RegionGeometryError("acis-polygon-invalid")
    if not polygon.is_valid:
        repaired = repair_roundoff_self_intersection(polygon)
        if repaired is None:
            raise RegionGeometryError("acis-polygon-invalid")
        return repaired
    return polygon
