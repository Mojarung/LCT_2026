"""Check mask import and remaining geometry gaps on an unchanged source DXF."""

# ruff: noqa: INP001, T201 - reproducible local diagnostic without source coordinates

from __future__ import annotations

import argparse
import json
import resource
import time
from collections import Counter
from pathlib import Path

from shapely.geometry import box

from green.infrastructure.cad.reader import EzdxfSceneReader


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--scope", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    started = time.perf_counter()
    scene = EzdxfSceneReader().read(args.source)
    masks = [feature for feature in scene.features if feature.source_entity_type == "WIPEOUT"]
    bounds = json.loads(args.scope.read_text())["boundary"]["bounds"] if args.scope else None
    window = box(*bounds) if bounds else None
    gaps_by_type: Counter[str] = Counter()
    for gap in scene.read_diagnostics.geometry_gaps:
        gaps_by_type[gap.entity_type] += gap.count
    result = {
        "source_sha256": scene.source_sha256,
        "features": len(scene.features),
        "masks": len(masks),
        "masks_in_work_bbox": sum(mask.geometry.intersects(window) for mask in masks)
        if window is not None
        else None,
        "mask_area_m2": round(sum(mask.geometry.area for mask in masks), 3),
        "mask_layers": dict(Counter(mask.layer for mask in masks)),
        "gap_count": sum(gap.count for gap in scene.read_diagnostics.geometry_gaps),
        "gaps_by_type": dict(gaps_by_type),
        "seconds": round(time.perf_counter() - started, 3),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(result)


if __name__ == "__main__":
    main()
