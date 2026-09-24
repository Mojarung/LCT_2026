"""Measure strict reading and planning on one fixed street with a polygonal REGION."""

# ruff: noqa: INP001, T201 - standalone reproducible research driver

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import resource
import sys
import time
from collections import Counter
from pathlib import Path

from green.application.errors import InputError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings


def _peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024) if platform.system() == "Darwin" else peak / 1024, 2)


def main() -> None:  # noqa: C901 - standalone benchmark has optional baseline loading
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--read-only", action="store_true")
    parser.add_argument("--reader-file", type=Path)
    parser.add_argument("--region-module-file", type=Path)
    args = parser.parse_args()
    started = time.perf_counter()
    container = build_container(Settings(config_dir=args.config, runs_dir=args.out / "runs"))
    reader = container.reader
    if args.reader_file is not None:
        if not args.read_only:
            parser.error("--reader-file is available only with --read-only")
        if args.region_module_file is not None:
            region_spec = importlib.util.spec_from_file_location(
                "green.infrastructure.cad.region_geometry", args.region_module_file
            )
            if region_spec is None or region_spec.loader is None:
                raise RuntimeError("Cannot load the requested REGION module")
            region_module = importlib.util.module_from_spec(region_spec)
            sys.modules[region_spec.name] = region_module
            region_spec.loader.exec_module(region_module)
        spec = importlib.util.spec_from_file_location("baseline_cad_reader", args.reader_file)
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load the requested reader module")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        reader = module.EzdxfSceneReader()
    scene = reader.read(args.source)
    read_s = time.perf_counter() - started
    region_reasons: Counter[str] = Counter()
    for gap in scene.read_diagnostics.geometry_gaps:
        if gap.entity_type == "REGION":
            region_reasons[gap.reason] += gap.count
    params = container.profiles.load("strict", {"max_rejections": 50})
    result: dict[str, object] = {
        "source_sha256": hashlib.sha256(args.source.read_bytes()).hexdigest(),
        "reader_file": str(args.reader_file) if args.reader_file else None,
        "read_s": round(read_s, 3),
        "region_features": sum(f.source_entity_type == "REGION" for f in scene.features),
        "region_gaps": sum(
            gap.count for gap in scene.read_diagnostics.geometry_gaps if gap.entity_type == "REGION"
        ),
        "region_gap_reasons": dict(region_reasons),
        "all_geometry_gaps": sum(gap.count for gap in scene.read_diagnostics.geometry_gaps),
    }
    if args.read_only:
        result["elapsed_s"] = round(time.perf_counter() - started, 3)
        result["peak_rss_mb"] = _peak_rss_mb()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    try:
        report = container.use_case.execute(
            PlanRequest("region-polygon", args.source, args.out, "strict", params)
        )
    except InputError as exc:
        result["plan_status"] = "rejected"
        result["rejection"] = str(exc)
    else:
        placements = [
            (plant.x, plant.y, plant.species.code) for plant in report.plan.placements
        ]
        result.update(
            plan_status="completed",
            placement_count=len(placements),
            species_counts=dict(Counter(species for _, _, species in placements)),
            placements_sha256=hashlib.sha256(
                json.dumps(placements, ensure_ascii=False).encode()
            ).hexdigest(),
            quality_index=report.plan.quality.index if report.plan.quality else None,
            plan_validation_ok=report.validation.ok if report.validation else None,
            integrity_ok=report.integrity.ok,
            export_validation_ok=report.export_validation.ok
            if report.export_validation
            else None,
        )
    result.update(
        elapsed_s=round(time.perf_counter() - started, 3),
        peak_rss_mb=_peak_rss_mb(),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
