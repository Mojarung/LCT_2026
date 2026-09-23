"""Read local DXFs and record approximation coverage without CAD coordinates."""
# ruff: noqa: INP001, T201 - standalone research driver

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

from green.infrastructure.cad.reader import EzdxfSceneReader

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    if not sys.argv[1:]:
        raise SystemExit("Usage: survey_curve_errors.py SOURCE.dxf [SOURCE.dxf ...]")
    rows = []
    for arg in sys.argv[1:]:
        begin = time.perf_counter()
        source = Path(arg)
        scene = EzdxfSceneReader().read(source)
        gaps: Counter[str] = Counter()
        for gap in scene.read_diagnostics.geometry_gaps:
            gaps[f"{gap.entity_type}:{gap.reason}"] += gap.count
        row = {
            "name": source.name,
            "source_sha256": scene.source_sha256,
            "features": len(scene.features),
            "bounded_approximations": scene.read_diagnostics.approximation_features,
            "max_error_m": scene.read_diagnostics.max_approximation_error_m,
            "unbounded_features": sum(f.geometry_error_m is None for f in scene.features),
            "geometry_gaps": dict(gaps),
            "seconds": round(time.perf_counter() - begin, 4),
        }
        rows.append(row)
        print(row, flush=True)
    target = ROOT / "docs/research/verified-pipeline/curve_survey.json"
    target.write_text(
        json.dumps(
            {
                "scope": (
                    "Local curve representation bounds and explicit gaps; "
                    "not semantic accuracy, original DWG fidelity, or survey precision."
                ),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
