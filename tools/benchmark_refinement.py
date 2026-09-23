"""Compare bounded deletion search with complete portfolio plans on declared scenes."""
# ruff: noqa: INP001, T201, S101 - standalone reproducible experiment

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from benchmark_placement import _scene

from green.application.assortment.summary import refresh_summaries
from green.application.explain import explain
from green.application.quality import assess
from green.application.refinement import refine_plan
from green.application.use_case import PlanRequest
from green.application.validation import validate_plan
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

if TYPE_CHECKING:
    from green.application.validation import PlanValidation
    from green.bootstrap.container import Container
    from green.domain.planting import Plan

ROOT = Path(__file__).resolve().parents[1]
CASES = [
    (name, angle) for name in ("strip", "crossing", "courtyard") for angle in (0.0, 0.37, 0.83)
]


def _counts(plan: Plan) -> dict[str, int]:
    return {
        "trees": sum(p.species.is_tree for p in plan.placements),
        "shrubs": sum(p.species.is_shrub for p in plan.placements),
    }


def _run_case(container: Container, work: Path, name: str, angle: float, budget: int) -> dict:
    case = f"{name}-{angle}"
    source = work / f"{case}.dxf"
    _scene(source, name, angle)
    params = container.profiles.load("strict", {"placement_solver": "portfolio"})
    report = container.use_case.execute(
        PlanRequest(case, source, work / case / "base", "strict", params)
    )
    container.artifacts.save(work / case / "base", report)
    context = report.context
    assert context is not None
    assert report.validation is not None
    assert report.validation.ok
    assert report.plan.quality is not None
    assert report.plan.quality.index is not None
    existing = report.plan.assortment_summary.existing if report.plan.assortment_summary else None

    def check(candidate: Plan) -> tuple[Plan, PlanValidation]:
        validation = validate_plan(
            candidate,
            context.features,
            context.labels,
            context.rulebook,
            params,
            catalog=container.species.all(),
            existing=existing,
        )
        return assess(candidate, context.site(), params), validation

    started = time.perf_counter()
    refined, _, trace = refine_plan(report.plan, report.validation, check, max_attempts=budget)
    elapsed = time.perf_counter() - started
    refined = explain(refresh_summaries(refined, params, container.species.all()), context.rulebook)
    target = work / case / "refined"
    target.mkdir(parents=True, exist_ok=True)
    rebuilt = container.use_case.rebuild(context, refined, target)
    container.artifacts.save(target, rebuilt)
    assert rebuilt.validation is not None
    assert rebuilt.validation.ok
    assert rebuilt.integrity.ok
    assert rebuilt.export_validation is not None
    assert rebuilt.export_validation.ok
    assert refined.quality is not None
    assert refined.quality.index is not None
    return {
        "case": case,
        "source_sha256": report.source_sha256,
        "baseline_index": report.plan.quality.index,
        "final_index": refined.quality.index,
        "gain": round(refined.quality.index - report.plan.quality.index, 6),
        "before_counts": _counts(report.plan),
        "after_counts": _counts(refined),
        "baseline_terms": [asdict(t) for t in report.plan.quality.terms],
        "final_terms": [asdict(t) for t in refined.quality.terms],
        "accepted": [a.placement_id for a in trace.attempts if a.outcome == "accepted"],
        "refinement": asdict(trace),
        "refinement_s": round(elapsed, 4),
        "valid": True,
        "export_ok": True,
        "productive": bool(refined.placements),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=len(CASES))
    parser.add_argument("--attempts", type=int, default=32)
    args = parser.parse_args()
    if args.attempts < 0 or not 1 <= args.limit <= len(CASES):
        parser.error("attempts must be non-negative and limit must be 1..9")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    container = build_container(
        Settings(config_dir=ROOT / "config", runs_dir=args.work_dir / "runs")
    )
    rows = []
    for name, angle in CASES[: args.limit]:
        row = _run_case(container, args.work_dir, name, angle, args.attempts)
        rows.append(row)
        print(
            {
                k: v
                for k, v in row.items()
                if k not in {"refinement", "baseline_terms", "final_terms"}
            },
            flush=True,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "scope": (
                        "Single-deletion search: three synthetic geometries, three rotations. "
                        "Not recognition, global optimality, or expert aesthetic evaluation. "
                        "Independent feasibility/DXF checks; original artifacts retained. "
                        "Defined metrics cannot disappear."
                    ),
                    "max_attempts": args.attempts,
                    "rows": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    if not all(row["productive"] for row in rows):
        raise SystemExit("Known plantable scenes produced empty plans; investigate before adoption")


if __name__ == "__main__":
    main()
