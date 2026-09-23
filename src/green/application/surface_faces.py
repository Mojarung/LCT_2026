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


@dataclass(frozen=True, slots=True)
class FaceMaterials:
    soil: BaseGeometry
    paved: BaseGeometry
    unresolved: BaseGeometry
    count: int
    conflicts: int
    unassigned_labels: int
    open_edges: int


def closed_face_materials(
    lines: NDArray[np.object_], soil_xy: NDArray[np.float64], paved_xy: NDArray[np.float64]
) -> FaceMaterials:
    # Noding only splits actual intersections. No snapping or arbitrary bridge
    # may turn an unfinished contour into a positive planting region.
    noded = shapely.union_all(lines)
    polygons, cuts, dangles, invalid = shapely.polygonize_full(shapely.get_parts(noded))
    faces = shapely.get_parts(polygons)
    index = STRtree(faces)

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
    unresolved = (soil & paved) | affected
    return FaceMaterials(
        soil=shapely.union_all(faces[soil & ~unresolved]),
        paved=shapely.union_all(faces[paved & ~unresolved]),
        unresolved=shapely.union_all(faces[unresolved]),
        count=len(faces),
        conflicts=int((soil & paved).sum()),
        unassigned_labels=missed_soil + missed_paved,
        open_edges=sum(int(shapely.get_num_geometries(g)) for g in (cuts, dangles, invalid)),
    )
