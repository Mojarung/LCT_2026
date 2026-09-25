"""Compare row-species repair with its pre-change commit on identical synthetic DXF.

The scenes declare their classes; this is a composition regression benchmark, not
evidence that unknown real CAD layers are classified correctly or that a jury
will prefer the new design.
"""

# ruff: noqa: INP001, T201 - standalone experiment driver with a concise live result

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import resource
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, cast

from benchmark_placement import _scene

from green.application import assortment
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from green.application.assortment.assign import Assignment, Candidate
    from green.application.assortment.structures import Structure
    from green.application.params import PlanParams
    from green.domain.planting import Plan, Species

    type AssignFn = Callable[
        [
            Sequence[Candidate],
            Sequence[Structure],
            Mapping[str, Species],
            Mapping[str, int],
            PlanParams,
        ],
        Assignment,
    ]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "out/row-repair-benchmark"
RESULT = ROOT / "docs/research/verified-pipeline/row_repair_comparison.json"
BASELINE_COMMIT = "06517b1"
ANGLES = (0.0, 0.37, 0.83)
NAMES = ("strip", "crossing", "courtyard")


def _baseline_assign() -> AssignFn:
    git_binary = shutil.which("git")
    if git_binary is None:
        raise RuntimeError("git is required to load the recorded baseline")
    source = subprocess.check_output(  # noqa: S603 - fixed local git revision and path
        [git_binary, "show", f"{BASELINE_COMMIT}:src/green/application/assortment/assign.py"],
        cwd=ROOT,
    )
    name = "green.application.assortment.assign_baseline"
    module = ModuleType(name)
    module.__package__ = "green.application.assortment"
    sys.modules[name] = module
    exec(compile(source, name, "exec"), module.__dict__)  # noqa: S102 - trusted local git commit
    return cast("AssignFn", module.assign)


def _record(plan: Plan) -> dict[str, object]:
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for placement in plan.placements:
        info = placement.assortment
        if info is not None and info.structure_kind == "row" and info.structure_id:
            groups[info.structure_id].append(placement.species.code)
    mixed = {
        row_id: dict(Counter(codes)) for row_id, codes in groups.items() if len(set(codes)) > 1
    }
    quality = plan.quality
    if quality is None:
        raise ValueError("Complete plan has no quality report")
    terms = {term.key: term.score for term in quality.terms}
    summary = plan.assortment_summary
    if summary is None:
        raise ValueError("Complete plan has no assortment summary")
    return {
        "placements": len(plan.placements),
        "trees": sum(placement.species.is_tree for placement in plan.placements),
        "shrubs": sum(placement.species.is_shrub for placement in plan.placements),
        "species": dict(summary.counts),
        "quota_violations": list(summary.quota_violations),
        "row_count": len(groups),
        "mixed_rows": mixed,
        "index": quality.index,
        "row_score": terms.get("rows"),
        "fit_score": terms.get("fit"),
    }


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    baseline = _baseline_assign()
    current = assortment.assign
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=OUTPUT / "runs"))
    sources: dict[tuple[str, float], Path] = {}
    for name in NAMES:
        for angle in ANGLES:
            path = OUTPUT / "inputs" / f"{name}-{angle}.dxf"
            path.parent.mkdir(parents=True, exist_ok=True)
            _scene(path, name, angle)
            sources[(name, angle)] = path

    def compare(name: str, angle: float, solver: str) -> dict[str, Any]:
        source = sources[(name, angle)]
        source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
        params = container.profiles.load(
            "strict", {"placement_solver": solver, "placement_time_limit_s": 5.0}
        )
        pair: list[dict[str, Any]] = []
        for label, method in (("baseline", baseline), ("repaired", current)):
            assortment.assign = method  # ty: ignore[invalid-assignment] - controlled comparison
            started = time.perf_counter()
            report = container.use_case.execute(
                PlanRequest(
                    f"{name}-{angle}-{solver}-{label}",
                    source,
                    OUTPUT / "runs" / f"{name}-{angle}-{solver}-{label}",
                    "strict",
                    params,
                )
            )
            evidence = _record(report.plan)
            evidence.update(
                ok=bool(
                    report.validation
                    and report.validation.ok
                    and report.integrity.ok
                    and report.export_validation
                    and report.export_validation.ok
                ),
                geometry_gaps=sum(gap.count for gap in report.read_diagnostics.geometry_gaps),
                semantics_ready=bool(report.classification and report.classification.ready),
                seconds=round(time.perf_counter() - started, 3),
            )
            pair.append(evidence)
        before, after = pair
        return {
            "case": f"{name}-{angle}",
            "placement_solver": solver,
            "source_sha256": source_sha,
            "baseline": before,
            "repaired": after,
            "same_species_counts": before["species"] == after["species"],
        }

    try:
        rotations = [compare(name, angle, "greedy") for name in NAMES for angle in ANGLES]
        solvers = [
            compare(name, 0.0, solver)
            for name in NAMES
            for solver in ("greedy", "milp", "portfolio")
        ]
    finally:
        assortment.assign = current
    report = {
        "scope": (
            "Declared synthetic semantics and a flattened DXF pipeline, including independent "
            "plan and export validation. Same source SHA within each pair; no real-CAD semantic "
            "accuracy or expert aesthetic claim. Timings are single runs."
        ),
        "baseline_commit": BASELINE_COMMIT,
        "current_assign_sha256": hashlib.sha256(
            (ROOT / "src/green/application/assortment/assign.py").read_bytes()
        ).hexdigest(),
        "scipy_version": importlib.metadata.version("scipy"),
        "rotations": rotations,
        "solver_variants": solvers,
        "batch_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    RESULT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    ok = True
    for row in (*rotations, *solvers):
        before, after = row["baseline"], row["repaired"]
        for version in (before, after):
            ok &= bool(
                version["ok"]
                and version["semantics_ready"]
                and not version["geometry_gaps"]
                and not version["quota_violations"]
            )
        ok &= before["placements"] == after["placements"]
        ok &= after["index"] + 1e-9 >= before["index"]
        if before["row_score"] is not None and after["row_score"] is not None:
            ok &= after["row_score"] + 1e-9 >= before["row_score"]
    for row in rotations:
        before, after = row["baseline"], row["repaired"]
        print(
            row["case"],
            f"mixed {len(before['mixed_rows'])}->{len(after['mixed_rows'])}",
            f"index {before['index']:.6f}->{after['index']:.6f}",
        )
    print(f"comparison={RESULT} complete={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
