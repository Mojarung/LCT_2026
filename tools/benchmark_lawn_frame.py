"""Compare the added soil-frame family against all retained legacy variants."""
# ruff: noqa: INP001, T201, S101 - reproducible experiment with independent certificates

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path

from benchmark_placement import _scene

from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    container = build_container(
        Settings(config_dir=ROOT / "config", runs_dir=args.work_dir / "runs")
    )
    params = container.profiles.load("strict", {"placement_solver": "portfolio"})
    rows = []
    for name in ("strip", "crossing", "courtyard"):
        for angle in (0.0, 0.37, 0.83):
            case = f"{name}-{angle}"
            source = args.work_dir / f"{case}.dxf"
            _scene(source, name, angle)
            begin = time.perf_counter()
            report = container.use_case.execute(
                PlanRequest(case, source, args.work_dir / case, "strict", params)
            )
            container.artifacts.save(args.work_dir / case, report)
            assert report.validation is not None
            assert report.validation.ok
            assert report.integrity.ok
            assert report.export_validation is not None
            assert report.export_validation.ok
            assert report.plan.placements
            portfolio = report.plan.portfolio
            assert portfolio is not None
            legacy = [
                v.quality_index
                for v in portfolio.variants
                if v.lawn_anchor == "raster" and v.valid and v.quality_index is not None
            ]
            assert legacy
            baseline = max(legacy)
            assert report.plan.quality is not None
            score = report.plan.quality.index
            assert score is not None
            assert score >= baseline
            row = {
                "case": case,
                "source_sha256": report.source_sha256,
                "legacy_best": baseline,
                "chosen": portfolio.chosen,
                "index": score,
                "gain": round(score - baseline, 6),
                "variants": [asdict(v) for v in portfolio.variants],
                "all_certificates_ok": True,
                "seconds": round(time.perf_counter() - begin, 3),
            }
            rows.append(row)
            print({k: v for k, v in row.items() if k != "variants"}, flush=True)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(
                    {
                        "scope": (
                            "Three declared synthetic scenes at three angles; best complete plan "
                            "among retained legacy and added soil-frame variants. Not recognition "
                            "accuracy, rotation invariance of the full pipeline, "
                            "or global aesthetic optimality."
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
