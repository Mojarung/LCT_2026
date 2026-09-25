"""Measure a local DXF semantic-review artifact without publishing customer CAD."""

# ruff: noqa: INP001, T201 - standalone local diagnostic

from __future__ import annotations

import argparse
import json
import resource
import time
from dataclasses import asdict
from pathlib import Path

import orjson

from green.application.classification import classification_report, classify_scene
from green.application.input_quality import require_complete_geometry
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource
from green.infrastructure.reports.semantic_review import save_review_geometry

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    began = time.perf_counter()
    raw = EzdxfSceneReader().read(args.source)
    require_complete_geometry(raw)
    read_s = time.perf_counter() - began
    rules = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    scene, _ = classify_scene(raw, rules)
    report = classification_report(scene, rules)
    classify_s = time.perf_counter() - began - read_s
    args.work_dir.mkdir(parents=True, exist_ok=True)
    summary = orjson.dumps({"ready": report.ready, **asdict(report)})
    (args.work_dir / "classification.json").write_bytes(summary)
    saved = save_review_geometry(args.work_dir, report, scene, None)
    result = {
        "source_sha256": scene.source_sha256,
        "features": len(scene.features),
        "unresolved_features": report.unresolved_features,
        "unresolved_work_intersections": report.unresolved_work_intersections,
        "geojson_bytes": saved["semantic-review.geojson"].stat().st_size,
        "classification_json_bytes": len(summary),
        "read_seconds": round(read_s, 3),
        "classify_seconds": round(classify_s, 3),
        "review_seconds": round(time.perf_counter() - began - read_s - classify_s, 3),
        "peak_rss_bytes_macos": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(result)


if __name__ == "__main__":
    main()
