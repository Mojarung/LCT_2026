"""Compare fixed local grids under explicit project surface interpretations.

Research only: reference signs select diagnostic windows, never training labels.
Full-scene obstacles are retained. No scenario certifies soil or class accuracy.
"""

# ruff: noqa: INP001, T201
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

import numpy as np
import shapely
from shapely.geometry import box
from verify_reference_surfaces import _signs

from green.application.classification import (
    classification_report,
    classify_scene,
    promote_unknown_lines,
)
from green.application.constraints import ConstraintIndex
from green.application.diameters import assign_diameters
from green.application.input_quality import require_complete_geometry
from green.application.params import active_distance_rules
from green.application.surfaces import build_surface_map
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.norms import PlantingType
from green.domain.planting import CheckOutcome, Verdict


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface-dxf", type=Path, required=True)
    parser.add_argument("--plant-dxf", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    container = build_container(Settings(config_dir=Path("config")))
    raw = container.reader.read(args.surface_dxf)
    require_complete_geometry(raw)
    reference = container.reader.read(args.plant_dxf)
    signs = _signs(reference, r"Растения фр\s*([1-6])")
    patches = {}
    for fragment in (2, 4, 6):
        instance, center = min(signs[fragment], key=lambda item: str(item[0].ref))
        offsets = np.arange(-6.75, 7, 0.5)
        xx, yy = np.meshgrid(offsets + center.x, offsets + center.y)
        patches[str(fragment)] = (
            str(instance.ref),
            box(center.x - 7, center.y - 7, center.x + 7, center.y + 7),
            shapely.points(np.column_stack((xx.ravel(), yy.ravel()))),
        )
    rows = []
    for scenario in ("automatic", "lawn", "lawn_edging", "lawn_mulch_edging"):
        assignments = {
            str(f.ref): "lawn"
            for f in raw.features
            if f.source_entity_type == "HATCH"
            and not f.uncertain_footprint
            and scenario != "automatic"
            and (
                re.search(r"Газон фр\s*[1-6]", f.layer, re.IGNORECASE)
                or ("mulch" in scenario and re.search(r"Щепа фр\s*[1-6]", f.layer, re.IGNORECASE))
            )
        }
        layers = {
            f.layer: "pavement_edge"
            for f in raw.features
            if "edging" in scenario and "Новый_! Лента" in f.layer
        }
        params = container.profiles.load(
            "strict",
            {
                "feature_classes": assignments,
                "layer_classes": layers,
                "semantic_source_sha256": raw.source_sha256,
                "require_known_objects": False,
            },
        )
        classified, _ = classify_scene(raw, container.layers.load(), params)
        ready = classification_report(classified, container.layers.load(), params).ready
        classified = promote_unknown_lines(classified)
        features = assign_diameters(
            classified.features, classified.labels, params.label_search_radius_m
        )
        for kind in (PlantingType.TREE, PlantingType.SHRUB):
            effective = replace(params, planting_type=kind)
            index = ConstraintIndex(
                features,
                active_distance_rules(container.rules.load(), effective),
                require_utility_data=True,
                require_soil=True,
                require_work_boundary=True,
                planting_radius_m=effective.footprint_radius_m,
            )
            index.surface = build_surface_map(
                features,
                classified.labels,
                index.boundary,
                params.surface_cell_m,
                inference_mode=params.surface_inference_mode,
            )
            for fragment, (ref, window, points) in patches.items():
                fit = index.plantable(points)
                batch = index.evaluate(points[fit])
                failures = Counter(
                    check.rule_id
                    for i in range(len(batch))
                    for check in batch.checks(i)
                    if check.outcome in (CheckOutcome.FAIL, CheckOutcome.NO_DATA)
                )
                rows.append(
                    {
                        "scenario": scenario,
                        "fragment": int(fragment),
                        "planting_type": kind.value,
                        "reference_sign": ref,
                        "grid_points": len(points),
                        "surface_boundary_fit": int(fit.sum()),
                        "norm_allowed": sum(
                            batch.verdict(i) is Verdict.ALLOWED for i in range(len(batch))
                        ),
                        "norm_verdicts": dict(
                            Counter(batch.verdict(i).value for i in range(len(batch)))
                        ),
                        "failed_rules": dict(failures),
                        "semantics_ready": ready,
                        "intersecting_classes": dict(
                            Counter(
                                f.object_class.value
                                for f in features
                                if f.geometry.intersects(window)
                            )
                        ),
                    }
                )
    output = {
        "scope": (
            "Three 14m windows around deterministically selected project signs; 0.5m grid. "
            "Counts are candidate points, not plant counts or area accuracy. Manual scenarios "
            "represent proposed surface design; mulch soil and remaining semantics are "
            "unverified. Automatic rows bypass the semantic stop for diagnosis only. "
            "Reference geometry gaps outside selected signs are not used as planting input."
        ),
        "surface_sha256": raw.source_sha256,
        "reference_sha256": reference.source_sha256,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    for row in rows:
        print(
            row["scenario"],
            row["fragment"],
            row["planting_type"],
            row["surface_boundary_fit"],
            row["norm_allowed"],
        )


if __name__ == "__main__":
    main()
