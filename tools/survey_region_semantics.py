"""Measure how newly decoded curved REGIONs affect default CAD classification."""

# ruff: noqa: INP001, T201 - standalone research diagnostic

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import shapely

from green.application.classification import classify_scene
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.objects import ObjectClass


def survey(source: Path, config: Path) -> dict:
    container = build_container(Settings(config_dir=config))
    scene, _ = classify_scene(container.reader.read(source), container.layers.load())
    curved = [
        feature
        for feature in scene.features
        if feature.source_entity_type == "REGION" and feature.geometry_error_m
    ]
    lawn = [feature.geometry for feature in curved if feature.object_class is ObjectClass.LAWN]
    existing = [
        feature.geometry
        for feature in scene.features
        if feature.source_entity_type != "REGION"
        and feature.object_class is ObjectClass.LAWN
        and feature.geometry.geom_type in {"Polygon", "MultiPolygon"}
    ]
    lawn_union = shapely.union_all(lawn)
    existing_union = shapely.union_all(existing)
    classes = Counter(str(feature.object_class) for feature in curved)
    return {
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "curved_region_count": len(curved),
        "class_counts": dict(classes),
        "curved_lawn_union_area_m2": round(lawn_union.area, 6),
        "curved_lawn_outside_other_lawn_m2": round(lawn_union.difference(existing_union).area, 6),
        "largest_curved_lawn_area_m2": round(max((shape.area for shape in lawn), default=0), 6),
        "scope": (
            "Name-rule classes are predictions, not ground truth. Small REGIONs in block "
            "symbols can be misclassified as plantable soil."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = survey(args.source, args.config)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
