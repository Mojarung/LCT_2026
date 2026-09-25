"""Measure project plant symbols against raw lawn and mulch HATCH geometry.

This is a diagnostic for a supplied project pair, not a soil or norm certificate.
Plant positions are read from drawn concentric rings, independently of the
planting generator and the layer classifier. Output contains aggregates only.
"""

# ruff: noqa: INP001, T201 - standalone local diagnostic for supplied CAD

from __future__ import annotations

import argparse
import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

from shapely.geometry import Point
from shapely.ops import unary_union

from green.application.input_quality import require_complete_geometry
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from green.domain.objects import Feature, InsertInstance, Scene

_CENTRE_TOLERANCE_M = 0.02
_MIN_RINGS = 2
_SHRUB_RADIUS_M = 0.5
_TREE_RADIUS_M = 1.6


def _surfaces(scene: Scene, expression: str) -> dict[int, BaseGeometry]:
    pattern = re.compile(expression, re.IGNORECASE)
    parts = defaultdict(list)
    for feature in scene.features:
        match = pattern.search(feature.layer)
        if (
            match is not None
            and feature.source_entity_type == "HATCH"
            and not feature.uncertain_footprint
        ):
            parts[int(match.group(1))].append(feature.geometry)
    return {fragment: unary_union(geometries) for fragment, geometries in parts.items()}


def _signs(scene: Scene, expression: str) -> dict[int, list[tuple[InsertInstance, Point]]]:
    pattern = re.compile(expression, re.IGNORECASE)
    grouped: dict[str, list[Feature]] = defaultdict(list)
    instances: dict[str, tuple[int, InsertInstance]] = {}
    for feature in scene.features:
        for instance in feature.insert_chain:
            match = pattern.search(instance.declared_layer)
            if match is None:
                continue
            key = str(instance.ref)
            grouped[key].append(feature)
            instances[key] = int(match.group(1)), instance
            break
    result = defaultdict(list)
    for key, features in grouped.items():
        centres = [
            feature.circle_center_m
            for feature in features
            if feature.source_entity_type == "CIRCLE" and feature.circle_center_m is not None
        ]
        if len(centres) < _MIN_RINGS:
            raise ValueError(f"Plant INSERT {key} has fewer than two drawn rings")
        x = math.fsum(point[0] for point in centres) / len(centres)
        y = math.fsum(point[1] for point in centres) / len(centres)
        if any(math.hypot(point[0] - x, point[1] - y) > _CENTRE_TOLERANCE_M for point in centres):
            raise ValueError(f"Plant INSERT {key} has nonconcentric rings")
        fragment, instance = instances[key]
        result[fragment].append((instance, Point(x, y)))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface-dxf", type=Path, required=True)
    parser.add_argument("--plant-dxf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plant-layer", default=r"Растения фр\s*([1-6])")
    parser.add_argument("--lawn-layer", default=r"Газон фр\s*([1-6])")
    parser.add_argument("--mulch-layer", default=r"Щепа фр\s*([1-6])")
    args = parser.parse_args()

    reader = EzdxfSceneReader()
    surface_scene = reader.read(args.surface_dxf)
    require_complete_geometry(surface_scene)
    plant_scene = reader.read(args.plant_dxf)
    lawn = _surfaces(surface_scene, args.lawn_layer)
    mulch = _surfaces(surface_scene, args.mulch_layer)
    signs = _signs(plant_scene, args.plant_layer)
    rows = []
    for fragment, plants in sorted(signs.items()):
        if fragment not in lawn or fragment not in mulch:
            raise ValueError(f"Fragment {fragment}: missing lawn or mulch HATCH")
        combined = lawn[fragment].union(mulch[fragment])
        rows.append(
            {
                "fragment": fragment,
                "reference_signs": len(plants),
                "lawn_m2_union": round(lawn[fragment].area, 3),
                "mulch_m2_union": round(mulch[fragment].area, 3),
                "centres_in_lawn": sum(lawn[fragment].covers(point) for _, point in plants),
                "centres_in_mulch": sum(mulch[fragment].covers(point) for _, point in plants),
                "centres_in_either": sum(combined.covers(point) for _, point in plants),
                "insertion_origins_in_lawn": sum(
                    lawn[fragment].covers(Point(instance.x, instance.y))
                    for instance, _ in plants
                ),
                "lawn_shrub_disk_fits": sum(
                    lawn[fragment].covers(point.buffer(_SHRUB_RADIUS_M))
                    for _, point in plants
                ),
                "lawn_tree_disk_fits": sum(
                    lawn[fragment].covers(point.buffer(_TREE_RADIUS_M))
                    for _, point in plants
                ),
                "combined_shrub_disk_fits": sum(
                    combined.covers(point.buffer(_SHRUB_RADIUS_M))
                    for _, point in plants
                ),
                "combined_tree_disk_fits": sum(
                    combined.covers(point.buffer(_TREE_RADIUS_M))
                    for _, point in plants
                ),
            }
        )
    output = {
        "scope": (
            "Same project pair: raw readable HATCHs and drawn concentric plant signs. "
            "Mulch is a surface cover, not by itself proof of rootable soil. "
            "Disk tests use geometry only, without obstacle clearances or species identity. "
            "Plant DXF may have unrelated geometry gaps."
        ),
        "surface_dxf_sha256": surface_scene.source_sha256,
        "plant_dxf_sha256": plant_scene.source_sha256,
        "surface_geometry_gaps": sum(
            gap.count for gap in surface_scene.read_diagnostics.geometry_gaps
        ),
        "plant_geometry_gaps": sum(gap.count for gap in plant_scene.read_diagnostics.geometry_gaps),
        "rows": rows,
        "totals": {
            key: sum(row[key] for row in rows)
            for key in (
                "reference_signs",
                "centres_in_lawn",
                "centres_in_mulch",
                "centres_in_either",
                "insertion_origins_in_lawn",
                "lawn_shrub_disk_fits",
                "lawn_tree_disk_fits",
                "combined_shrub_disk_fits",
                "combined_tree_disk_fits",
            )
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(output["totals"], ensure_ascii=False))


if __name__ == "__main__":
    main()
