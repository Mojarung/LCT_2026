"""Infer material only inside closed faces made from actual surface boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely import STRtree

if TYPE_CHECKING:
    from numpy.typing import NDArray
    from shapely.geometry.base import BaseGeometry

_MAX_ROUNDOFF_GRID_M = 1e-6


@dataclass(frozen=True, slots=True)
class FaceMaterials:
    soil: BaseGeometry
    paved: BaseGeometry
    unresolved: BaseGeometry
    paved_evidence: BaseGeometry
    count: int
    conflicts: int
    unassigned_labels: int
    open_edges: int
    unsupported_boundaries: int


def closed_face_materials(
    lines: NDArray[np.object_],
    soil_xy: NDArray[np.float64],
    paved_xy: NDArray[np.float64],
    *,
    material_lines: NDArray[np.object_],
) -> FaceMaterials:
    # Independent CAD transforms can round the same shared vertex differently.
    # A grid of four ULP at the drawing's coordinate scale joins only seams at
    # floating-point precision; larger gaps remain open. Never use a tolerance
    # larger than one micrometre in the drawing's metre coordinates.
    grid = _roundoff_grid(lines)
    noded = shapely.union_all(lines, grid_size=grid or None)
    polygons, cuts, dangles, invalid = shapely.polygonize_full(shapely.get_parts(noded))
    faces = shapely.get_parts(polygons)
    index = STRtree(faces)
    # A fence/rail/axis can cut a face or reserve an unknown hole, but cannot
    # establish a homogeneous material enclosure. Only the exterior needs
    # positive support: interior holes remain outside the assigned material.
    missing = shapely.difference(
        shapely.get_exterior_ring(faces), shapely.union_all(material_lines, grid_size=grid or None)
    )
    supported = shapely.is_empty(missing)

    def assigned(xy: NDArray[np.float64]) -> tuple[NDArray[np.bool_], int]:
        matches = index.query(shapely.points(xy), predicate="within")
        present = np.zeros(len(faces), dtype=bool)
        present[matches[1]] = True
        return present, len(xy) - len(np.unique(matches[0]))

    soil, missed_soil = assigned(soil_xy)
    paved, missed_paved = assigned(paved_xy)
    # An unfinished material separator inside an otherwise closed face means
    # the outer face may contain several materials. Outside tails are harmless.
    incomplete = shapely.get_parts(shapely.union_all([cuts, dangles, invalid]))
    pairs = index.query(incomplete, predicate="intersects")
    affected = np.zeros(len(faces), dtype=bool)
    if pairs.shape[1]:
        pieces = shapely.intersection(incomplete[pairs[0]], faces[pairs[1]])
        inside = shapely.difference(pieces, shapely.boundary(faces[pairs[1]]))
        affected[pairs[1][shapely.length(inside) > 0]] = True
    unresolved = (soil & paved) | affected | ~supported
    return FaceMaterials(
        soil=shapely.union_all(faces[soil & ~unresolved]),
        paved=shapely.union_all(faces[paved & ~unresolved]),
        unresolved=shapely.union_all(faces[unresolved]),
        # Contrary evidence still challenges a declared lawn when incomplete
        # linework prevents positively assigning the face's material.
        paved_evidence=shapely.union_all(faces[paved]),
        count=len(faces),
        conflicts=int((soil & paved).sum()),
        unassigned_labels=missed_soil + missed_paved,
        open_edges=sum(int(shapely.get_num_geometries(g)) for g in (cuts, dangles, invalid)),
        unsupported_boundaries=int((~supported).sum()),
    )


def _roundoff_grid(lines: NDArray[np.object_]) -> float:
    if not len(lines):
        return 0.0
    bounds = shapely.total_bounds(lines)
    if not np.isfinite(bounds).all():
        return 0.0
    scale = float(np.max(np.abs(bounds)))
    if scale == 0:
        return 0.0
    grid = 4 * float(np.spacing(scale))
    return grid if 0 < grid <= _MAX_ROUNDOFF_GRID_M else 0.0
