"""Run one frozen source with either checkout for a side-by-side pipeline audit.

Invoke in a fresh process with PYTHONPATH pointing at the checkout's src directory.
The output records observed behavior; it does not certify semantic correctness.
"""

# ruff: noqa: INP001, BLE001, T201 - standalone evidence capture must report failures

from __future__ import annotations

import argparse
import json
import resource
import time
import traceback
from collections import Counter
from pathlib import Path

from green.application.classification import classification_report, classify_scene
from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--variant", required=True)
    parser.add_argument("--overrides", default="{}")
    parser.add_argument("--stage", choices=("read", "plan"), default="plan")
    args = parser.parse_args()
    overrides = json.loads(args.overrides)
    started = time.perf_counter()
    args.out.mkdir(parents=True, exist_ok=True)
    row = {
        "variant": args.variant,
        "source": str(args.source.resolve()),
        "source_bytes": args.source.stat().st_size,
        "overrides": overrides,
        "stage": args.stage,
        "status": "complete",
    }
    try:
        container = build_container(
            Settings(config_dir=args.root / "config", runs_dir=args.out / "runs", converter="none")
        )
        params = container.profiles.load("strict", overrides)
        row["effective_params"] = {
            key: getattr(params, key, None)
            for key in (
                "spacing_m",
                "infer_unknown",
                "assume_unknown_geometry",
                "require_known_objects",
                "require_soil",
                "surface_inference_mode",
                "placement_solver",
                "zones",
            )
        }
        if args.stage == "read":
            scene = container.reader.read(args.source, unit=params.drawing_unit)
            diagnostics = scene.read_diagnostics
            row.update(
                source_sha256=scene.source_sha256,
                features=len(scene.features),
                labels=len(scene.labels),
                symbols=len(getattr(scene, "symbols", ())),
                visited=sum(diagnostics.visited_by_type.values()),
                skipped=sum(diagnostics.skipped_by_type.values()),
                bounded_uncertainty=sum(
                    getattr(diagnostics, "bounded_uncertainty_by_type", {}).values()
                ),
                geometry_gaps=len(diagnostics.geometry_gaps),
                unresolved_xrefs=len(diagnostics.unresolved_xrefs),
                max_approximation_error_m=diagnostics.max_approximation_error_m,
                classes=dict(Counter(str(f.object_class) for f in scene.features)),
            )
            try:
                require_complete_geometry(scene)
                row["geometry_gate"] = "pass"
            except InputError as error:
                row["geometry_gate"] = "reject"
                row["geometry_error"] = str(error)[:1000]
            classified, _ = classify_scene(scene, container.layers.load(), params)
            report = classification_report(classified, container.layers.load(), params)
            row.update(
                semantic_ready=report.ready,
                unresolved_features=report.unresolved_features,
                classified_classes=dict(Counter(str(f.object_class) for f in classified.features)),
                classification_methods=dict(
                    Counter(
                        f.classification.method if f.classification is not None else "unmatched"
                        for f in classified.features
                    )
                ),
                special_features=[
                    {
                        "entity_type": f.source_entity_type,
                        "class": str(f.object_class),
                        "method": f.classification.method if f.classification else None,
                        "uncertain": bool(getattr(f, "uncertain_footprint", False))
                        or getattr(f, "uncertainty_footprint", None) is not None,
                        "uncertainty_area_m2": round(
                            getattr(f, "uncertainty_footprint", None).area, 4
                        )
                        if getattr(f, "uncertainty_footprint", None) is not None
                        else None,
                        "geometry_type": f.geometry.geom_type,
                        "area_m2": round(f.geometry.area, 4),
                        "bounds": [round(v, 4) for v in f.geometry.bounds],
                    }
                    for f in classified.features
                    if f.source_entity_type in {"HATCH", "REGION", "MLINE"}
                ][:100],
            )
        else:
            report = container.use_case.execute(
                PlanRequest(args.variant, args.source, args.out / "run", "strict", params)
            )
            container.artifacts.save(args.out / "run", report)
            row.update(
                status="complete",
                source_sha256=report.source_sha256,
                summary=report.summary(),
                quality_index=report.plan.quality.index if report.plan.quality else None,
                unresolved_features=(
                    report.classification.unresolved_features if report.classification else None
                ),
                geometry_gaps=len(report.read_diagnostics.geometry_gaps),
                unresolved_xrefs=len(report.read_diagnostics.unresolved_xrefs),
                placements=[
                    {
                        "x": p.x,
                        "y": p.y,
                        "species": p.species.code,
                        "tree": p.species.is_tree,
                        "shrub": p.species.is_shrub,
                    }
                    for p in report.plan.placements
                ],
            )
    except Exception as error:  # experiment must preserve the actual failure
        row.update(status="error", error_type=type(error).__name__, error=str(error)[:2000])
        row["traceback"] = traceback.format_exc(limit=8)
    row["elapsed_s"] = round(time.perf_counter() - started, 3)
    row["peak_rss_mib_macos"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1)
    (args.out / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                k: row.get(k)
                for k in (
                    "variant",
                    "stage",
                    "status",
                    "features",
                    "geometry_gate",
                    "semantic_ready",
                    "unresolved_features",
                    "quality_index",
                    "elapsed_s",
                    "error_type",
                )
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
