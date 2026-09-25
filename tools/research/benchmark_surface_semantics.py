"""Compare identical project DXF runs with exact HATCH material assignments.

Diagnostic only: unmatched spatial objects remain unresolved. A completed plan
under require_known_objects=false cannot be presented as normatively safe.
"""

# ruff: noqa: INP001, T201 - standalone recorded CAD experiment

from __future__ import annotations

import argparse
import json
import re
import resource
import time
from collections import Counter
from pathlib import Path

from green.application.errors import InputError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--mode", choices=("none", "lawn", "lawn-mulch"), required=True)
    parser.add_argument(
        "--unknown-lines-as-utility", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--reviewed-garden-edging", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    container = build_container(Settings(config_dir=Path("config"), runs_dir=args.out / "runs"))
    scene = container.reader.read(args.source)
    classes = {}
    layer_classes = {}
    if args.reviewed_garden_edging:
        layer_classes = {
            feature.layer: "pavement_edge"
            for feature in scene.features
            if "Новый_! Лента" in feature.layer
        }
    for feature in scene.features:
        if feature.source_entity_type != "HATCH" or feature.uncertain_footprint:
            continue
        lawn = re.search(r"Газон фр\s*[1-6]", feature.layer, re.IGNORECASE)
        mulch = re.search(r"Щепа фр\s*[1-6]", feature.layer, re.IGNORECASE)
        if (lawn and args.mode != "none") or (mulch and args.mode == "lawn-mulch"):
            classes[str(feature.ref)] = "lawn"
    params = container.profiles.load(
        "strict",
        {
            "require_known_objects": False,
            "semantic_source_sha256": scene.source_sha256,
            "feature_classes": classes,
            "layer_classes": layer_classes,
            "placement_solver": "greedy",
            "zones": False,
            "unknown_lines_as_utility": args.unknown_lines_as_utility,
        },
    )
    result: dict[str, object] = {
        "scope": (
            "Exploratory semantic counterfactual on same DXF; exact HATCH overrides. "
            "Mulch eligibility is unverified, other unknown features remain unresolved. "
            "Greedy chosen in all modes; not a validated full-project plan."
        ),
        "mode": args.mode,
        "source_sha256": scene.source_sha256,
        "overridden_hatches": len(classes),
        "unknown_lines_as_utility": args.unknown_lines_as_utility,
        "reviewed_garden_edging_layers": len(layer_classes),
    }
    try:
        report = container.use_case.execute(
            PlanRequest(f"surface-{args.mode}", args.source, args.out, "strict", params)
        )
    except InputError as error:
        result.update(status="rejected", error=str(error))
    else:
        result.update(
            status="completed",
            placements=len(report.plan.placements),
            class_counts=report.class_counts,
            semantic_assignments_complete=(
                report.classification.ready if report.classification is not None else None
            ),
            validation_ok=report.validation.ok if report.validation is not None else None,
            summary=report.summary(),
            rejected_by_rule=dict(
                Counter(
                    check.rule_id
                    for rejection in report.plan.rejections
                    for check in rejection.blocking
                )
            ),
            rejected_by_note=dict(Counter(rejection.note for rejection in report.plan.rejections)),
            timings_ms={stage.stage: stage.ms for stage in report.timings},
        )
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "placements.json").write_text(
            json.dumps(
                [
                    {"x": placement.x, "y": placement.y, "species": placement.species.code}
                    for placement in report.plan.placements
                ],
                ensure_ascii=False,
            )
            + "\n"
        )
    result["elapsed_s"] = round(time.perf_counter() - started, 3)
    result["peak_rss_mb_macos"] = round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1048576, 2
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    keys = ("mode", "status", "placements", "error", "elapsed_s", "peak_rss_mb_macos")
    print(json.dumps({key: result.get(key) for key in keys}, ensure_ascii=False))


if __name__ == "__main__":
    main()
