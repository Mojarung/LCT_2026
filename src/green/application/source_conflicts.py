"""Advisory overlaps in classified input, independent of generated plantings.

Only trunk positions and explicit polygon interiors are evidence. A crown touching a
building, an open boundary, or an ambiguous strip symbol is not a trunk inside paving.
The result requests review; it neither changes the drawing nor certifies a violation.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

import shapely
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from green.domain.objects import Feature, ObjectClass, SourceRef

if TYPE_CHECKING:
    from collections.abc import Sequence

AREA_CLASSES = frozenset({ObjectClass.SIDEWALK, ObjectClass.ROAD, ObjectClass.BUILDING})
BOUNDARY_TOLERANCE_M = 0.05


@dataclass(frozen=True, slots=True)
class ConflictTarget:
    object_class: str
    ref: str
    layer: str
    depth_m: float


@dataclass(frozen=True, slots=True)
class SourceConflict:
    id: str
    x: float
    y: float
    tree_refs: tuple[str, ...]
    targets: tuple[ConflictTarget, ...]


@dataclass(frozen=True, slots=True)
class SourceConflicts:
    basis: str
    checked_trees: int
    checked_areas: int
    skipped_tree_features: int
    skipped_area_features: int
    boundary_tolerance_m: float
    items: tuple[SourceConflict, ...]
    version: int = 1

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def find_source_conflicts(features: Sequence[Feature], *, basis: str = "source") -> SourceConflicts:
    """Report unique trunk positions strictly inside classified closed areas.

    Coordinate grouping at 1 cm removes overlaid copies, including duplicate XREFs.
    Geometry approximation errors enlarge the boundary margin. Invalid/unknown geometry
    is skipped rather than repaired into an invented interior. Polygon holes are kept.
    """
    trees, areas, skipped_trees, skipped_areas = _candidates(features)

    index = STRtree([f.geometry for f in areas])
    found = []
    for (x, y), marks in sorted(trees.items()):
        point = Point(x, y)
        targets = []
        tree_error = max(f.geometry_error_m or 0 for f in marks) + 0.008  # cm snap diagonal
        for i in index.query(point, predicate="within"):
            area = areas[int(i)]
            depth = area.geometry.boundary.distance(point)
            tolerance = max(BOUNDARY_TOLERANCE_M, tree_error + (area.geometry_error_m or 0))
            if depth <= tolerance:
                continue
            uncertain = area.uncertainty_footprint
            if uncertain is not None and uncertain.intersects(point):
                continue
            targets.append(
                ConflictTarget(str(area.object_class), str(area.ref), area.layer, round(depth, 3))
            )
        if targets:
            key = hashlib.sha256(f"{x:.2f},{y:.2f}".encode()).hexdigest()[:16]
            found.append(
                SourceConflict(
                    id=f"source-{key}",
                    x=x,
                    y=y,
                    tree_refs=tuple(sorted({str(f.ref) for f in marks})),
                    targets=tuple(sorted(set(targets), key=lambda t: (t.object_class, t.ref))),
                )
            )
    return SourceConflicts(
        basis,
        len(trees),
        len(areas),
        skipped_trees,
        skipped_areas,
        BOUNDARY_TOLERANCE_M,
        tuple(found),
    )


def _candidates(
    features: Sequence[Feature],
) -> tuple[dict[tuple[float, float], list[Feature]], list[Feature], int, int]:
    trees: dict[tuple[float, float], list[Feature]] = {}
    areas: list[Feature] = []
    skipped_trees = skipped_areas = 0
    for feature in features:
        kind, geometry = feature.object_class, feature.geometry
        if kind != ObjectClass.EXISTING_TREE and kind not in AREA_CLASSES:
            continue
        valid = (
            geometry is not None
            and not geometry.is_empty
            and geometry.is_valid
            and feature.geometry_error_m is not None
            and math.isfinite(feature.geometry_error_m)
            and feature.geometry_error_m >= 0
        )
        if kind == ObjectClass.EXISTING_TREE:
            if (
                not valid
                or feature.source_entity_type in {"TREE_STRIP", "SHRUB_STRIP"}
                or geometry.geom_type not in {"Point", "MultiPoint"}
            ):
                skipped_trees += 1
                continue
            points = [geometry] if geometry.geom_type == "Point" else geometry.geoms
            for point in points:
                if math.isfinite(point.x) and math.isfinite(point.y):
                    trees.setdefault((round(point.x, 2), round(point.y, 2)), []).append(feature)
        elif not valid or geometry.geom_type not in {"Polygon", "MultiPolygon"}:
            skipped_areas += 1
        else:
            areas.append(feature)

    return trees, areas, skipped_trees, skipped_areas


def enrich_saved_basemap(data: dict[str, Any]) -> dict[str, Any]:
    """Read-only fallback for old runs: use the saved map and disclose its limits.

    New runs carry full-source results before simplification. Old runs can have reduced
    geometry, so their result cannot establish absence of conflicts in the original CAD.
    No stored artifact, input, placement, or validation result is changed here.
    """
    if data.get("source_conflicts") is not None:
        return data
    raw_tolerance = data.get("counts", {}).get("tolerance_m", 0.15)
    tolerance = float(raw_tolerance) if isinstance(raw_tolerance, (int, float)) else 0.15
    if not math.isfinite(tolerance) or tolerance < 0:
        tolerance = 0.15
    features = []
    for i, item in enumerate(data.get("features", [])):
        properties = item.get("properties", {})
        value = properties.get("class")
        if value not in {str(c) for c in AREA_CLASSES} | {str(ObjectClass.EXISTING_TREE)}:
            continue
        try:
            geometry = shape(item["geometry"])
        except KeyError, ValueError, TypeError, shapely.errors.GEOSException:
            continue
        kind = properties.get("vegetation_kind")
        ambiguous = kind in {"strip", "shrub_strip"} or (
            geometry.geom_type == "MultiPoint" and kind != "individual"
        )
        features.append(
            Feature(
                ref=SourceRef("saved-map", "00000000", str(i)),
                layer="",
                geometry=geometry,
                object_class=ObjectClass(value),
                geometry_error_m=0.008 if value == "existing_tree" else tolerance + 0.008,
                source_entity_type="TREE_STRIP" if ambiguous else geometry.geom_type,
            )
        )
    return {
        **data,
        "source_conflicts": find_source_conflicts(features, basis="saved_basemap").payload(),
    }
