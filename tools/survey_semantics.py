"""Count semantic assignments on local DXFs; no recognition accuracy claim.

Usage: python tools/survey_semantics.py [--output FILE] SOURCE [SOURCE ...]
Only hashes, filenames, counts and timings are persisted. Input CAD stays local.
"""
# ruff: noqa: INP001, T201 - standalone research driver

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from green.application.classification import classification_report, classify_scene
from green.application.constraints import work_boundary
from green.application.errors import InputError
from green.application.input_quality import require_complete_geometry
from green.domain.objects import ObjectClass
from green.infrastructure.cad.reader import EzdxfSceneReader
from green.infrastructure.config.repositories import YamlLayerMapSource

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = ROOT / "docs/research/verified-pipeline/semantic_survey.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, default=DEFAULT_TARGET)
    parser.add_argument(
        "--work-overlap",
        action="store_true",
        help="Count features intersecting the same work boundary used by placement",
    )
    args = parser.parse_args()
    rules = YamlLayerMapSource(ROOT / "config/layer_map.yaml").load()
    rows = []
    for source in args.sources:
        started = time.perf_counter()
        row: dict[str, object] = {"name": source.name}
        try:
            raw = EzdxfSceneReader().read(source)
            row["source_sha256"] = raw.source_sha256
            require_complete_geometry(raw)
            began = time.perf_counter()
            scene, _ = classify_scene(raw, rules)
            report = classification_report(scene, rules)
            unresolved = {ObjectClass.UNKNOWN, ObjectClass.UTILITY_UNKNOWN}
            row.update(
                import_complete=True,
                features=report.features,
                semantic_ready=report.ready,
                unresolved_features=report.unresolved_features,
                unresolved_layers=len(
                    {g.layer for g in report.groups if g.object_class in unresolved}
                ),
                unresolved_geometry=dict(
                    Counter(
                        f.geometry.geom_type for f in scene.features if f.object_class in unresolved
                    )
                ),
                methods=dict(
                    Counter(f.classification.method for f in scene.features if f.classification)
                ),
                classes=dict(Counter(f.object_class.value for f in scene.features)),
                classification_seconds=round(time.perf_counter() - began, 4),
            )
            if args.work_overlap:
                boundary = work_boundary(scene.features)
                if boundary is None:
                    row["work_overlap"] = {"boundary_found": False}
                else:
                    overlap = Counter()
                    unknown_layers: Counter[str] = Counter()
                    for feature in scene.features:
                        if boundary.intersects(feature.geometry):
                            overlap["features"] += 1
                            if feature.object_class in unresolved:
                                overlap["unresolved_features"] += 1
                                unknown_layers[feature.layer] += 1
                    row["work_overlap"] = {
                        "boundary_found": True,
                        "boundary_area_m2": round(boundary.area, 3),
                        **dict(overlap),
                        "top_unresolved_layers": unknown_layers.most_common(15),
                    }
        except InputError as error:
            row.update(import_complete=False, error=str(error))
        row["seconds"] = round(time.perf_counter() - started, 4)
        rows.append(row)
        print(row, flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(
            {
                "scope": (
                    "Assignment/completeness counts only, not semantic accuracy. "
                    "No independent annotated ground truth. Known names can still be wrong. "
                    "All DXFs read locally."
                ),
                "layer_map_fingerprint": rules.fingerprint,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
