"""Count geometry and norm gates for candidates on one explicitly mapped DXF.

Diagnostic only: the optional mulch mapping and unresolved semantics cannot
certify the resulting candidates as safe planting sites.
"""

# ruff: noqa: INP001, T201 - standalone diagnostic reuses generator candidates

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import shapely

from green.application.barriers import NEAR_M, barrier_distance
from green.application.classification import classify_scene, promote_unknown_lines
from green.application.constraints import ConstraintIndex
from green.application.diameters import assign_diameters
from green.application.input_quality import require_complete_geometry
from green.application.params import active_distance_rules
from green.application.placement import (
    GreedyPlantingStrategy,
    _curb_candidates,
    _curb_lines,
    _lawn_candidates,
)
from green.application.surfaces import build_surface_map
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.domain.planting import CheckOutcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--unknown-lines-as-utility", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    container = build_container(Settings(config_dir=Path("config")))
    source = container.reader.read(args.source)
    require_complete_geometry(source)
    explicit = {
        str(feature.ref): "lawn"
        for feature in source.features
        if feature.source_entity_type == "HATCH"
        and not feature.uncertain_footprint
        and re.search(r"(?:Газон|Щепа) фр\s*[1-6]", feature.layer, re.IGNORECASE)
    }
    params = container.profiles.load(
        "strict",
        {
            "require_known_objects": False,
            "semantic_source_sha256": source.source_sha256,
            "feature_classes": explicit,
            "placement_solver": "greedy",
            "zones": False,
            "unknown_lines_as_utility": args.unknown_lines_as_utility,
        },
    )
    scene, _ = classify_scene(source, container.layers.load(), params)
    if params.unknown_lines_as_utility:
        scene = promote_unknown_lines(scene)
    features = assign_diameters(scene.features, scene.labels, params.label_search_radius_m)
    species = container.species.get(params.species_code)
    rulebook = container.rules.load()
    rules = active_distance_rules(rulebook, params, species.name_lat)
    barrier = None
    if params.root_barriers:
        barrier = (
            barrier_distance(species.height_m) if params.assortment_mode == "single" else NEAR_M
        )
    index = ConstraintIndex(
        features,
        rules,
        require_utility_data=params.require_utility_data,
        barrier_distance_m=barrier,
        require_soil=params.require_soil,
        require_work_boundary=params.require_work_boundary,
        planting_radius_m=params.footprint_radius_m,
    )
    index.surface = build_surface_map(
        features,
        scene.labels,
        index.boundary,
        params.surface_cell_m,
        max_distance_m=params.surface_max_distance_m,
        ambiguity_m=params.surface_ambiguity_m,
        tree_distance_m=params.tree_seed_distance_m,
        inference_mode=params.surface_inference_mode,
    )
    reach = max((abs(offset) for offset in params.curb_offsets_m), default=0.0)
    modes = {
        "alley": _curb_candidates(_curb_lines(features, index.boundary, reach + 0.002), params),
        "lawn": _lawn_candidates(index.surface, params) if index.surface is not None else [],
    }
    by_ref = {str(feature.ref): feature for feature in features}
    counts = {}
    for mode, candidates in modes.items():
        points = shapely.points([(round(c.x, 3), round(c.y, 3)) for c in candidates])
        accepted = index.plantable(points)
        batch = index.evaluate(points[accepted])
        verdicts = Counter(batch.verdict(i).value for i in range(len(batch)))
        failures = Counter()
        nearest_layers = Counter()
        for i in range(len(batch)):
            for check in batch.checks(i):
                if check.outcome not in (CheckOutcome.FAIL, CheckOutcome.NO_DATA):
                    continue
                object_class = check.object_class.value if check.object_class else "none"
                failures[(check.rule_id, object_class)] += 1
                nearest = by_ref.get(str(check.nearest)) if check.nearest is not None else None
                if nearest is not None:
                    nearest_layers[(check.rule_id, nearest.layer)] += 1
        counts[mode] = {
            "candidates": len(candidates),
            "surface_boundary_plantable": int(np.count_nonzero(accepted)),
            "norm_verdicts_before_spacing": dict(verdicts),
            "failing_rules_before_spacing": [
                {"rule": rule, "class": object_class, "count": count}
                for (rule, object_class), count in failures.most_common()
            ],
            "failing_nearest_layers_top20": [
                {"rule": rule, "layer": layer, "count": count}
                for (rule, layer), count in nearest_layers.most_common(20)
            ],
        }
    greedy = GreedyPlantingStrategy().plan(features, scene.labels, rulebook, species, params)
    output = {
        "scope": (
            "Exact HATCH material counterfactual on one DXF. Counts precede greedy spacing, "
            "species assignment and independent validation; unknown semantics and mulch "
            "soil eligibility are unresolved."
        ),
        "source_sha256": source.source_sha256,
        "unknown_lines_as_utility": args.unknown_lines_as_utility,
        "explicit_lawn_hatches": len(explicit),
        "modes": counts,
        "greedy_before_assortment_placements": len(greedy.placements),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({mode: row["norm_verdicts_before_spacing"] for mode, row in counts.items()}))


if __name__ == "__main__":
    main()
