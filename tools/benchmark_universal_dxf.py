"""End-to-end metamorphic cases with declared geometry and deliberately opaque semantics.

Every input must first fail strict classification, then produce a nonempty checked
plan after exact, source-bound assignments. The oracle knows the synthetic street
in local metres and checks exported placements independently of surface inference.
No customer geometry or claimed recognition accuracy is involved.
"""
# ruff: noqa: INP001, T201 - standalone reproducible research driver

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf

from green.application.classification import ClassificationError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings
from green.infrastructure.cad.reader import EzdxfSceneReader

if TYPE_CHECKING:
    from typing import Any

    from green.application.results import RunReport

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "out/universal-dxf"
EPSILON_M = 0.002
MIN_TREES = 10
# 0.01 percentage point in the project's quality index, for this fixture family.
# Not a tolerance on regulatory distances or a bound for arbitrary CAD inputs.
QUALITY_EQUIVALENCE_TOLERANCE = 1e-4


@dataclass(frozen=True)
class Case:
    material: str
    unit: int
    unit_m: float
    angle: float
    shift: float
    mirror: int
    nested: bool
    single_layer: bool
    version: str
    curb_shape: str = "line"

    def world(self, x: float, y: float) -> tuple[float, float]:
        c, s = math.cos(math.radians(self.angle)), math.sin(math.radians(self.angle))
        return self.shift + self.mirror * x * c - y * s, -self.shift + self.mirror * x * s + y * c

    def local(self, x: float, y: float) -> tuple[float, float]:
        x, y = x - self.shift, y + self.shift
        c, s = math.cos(math.radians(self.angle)), math.sin(math.radians(self.angle))
        return self.mirror * (x * c + y * s), -x * s + y * c


def drawing(path: Path, case: Case) -> list[str]:
    doc = ezdxf.new(case.version)
    doc.units = case.unit
    target = doc.blocks.new("bx_17") if case.nested else doc.modelspace()
    roles = []

    def coordinate(x: float, y: float) -> tuple[float, float]:
        if not case.nested:
            x, y = case.world(x, y)
        return x / case.unit_m, y / case.unit_m

    def layer(role: str) -> str:
        name = "0" if case.single_layer else "z_" + hashlib.sha256(role.encode()).hexdigest()[:7]
        if name not in doc.layers:
            doc.layers.new(name)
        return name

    def area(role: str, bottom: float, top: float) -> None:
        target.add_lwpolyline(
            [
                coordinate(0, bottom),
                coordinate(120, bottom),
                coordinate(120, top),
                coordinate(0, top),
            ],
            close=True,
            dxfattribs={"layer": layer(role)},
        )
        roles.append(role)

    area("work_boundary", 0, 60)
    area("lawn" if case.material == "area" else "pavement_edge", 20, 55)
    area("road", 0, 20)
    area("building", 55, 60)
    for role, y in (("curb", 20), ("utility.water", 40)):
        if role == "curb" and case.curb_shape == "ring":
            area(role, 20, 55)
            continue
        target.add_line(coordinate(0, y), coordinate(120, y), dxfattribs={"layer": layer(role)})
        roles.append(role)
    for text, y, role in (("M-017", 30, "lawn"), ("d=300ст.", 40.5, "utility.water")):
        target.add_text(
            text,
            height=1 / case.unit_m,
            dxfattribs={"layer": layer(role), "insert": coordinate(60, y)},
        )
    if case.nested:
        middle = doc.blocks.new("bx_29")
        middle.add_blockref("bx_17", (0, 0))
        doc.modelspace().add_blockref(
            "bx_29",
            (case.shift / case.unit_m, -case.shift / case.unit_m),
            dxfattribs={"rotation": case.angle, "xscale": case.mirror},
        )
    doc.saveas(path)
    return roles


def oracle(report: RunReport, case: Case) -> list[str]:  # noqa: C901 - independent checks stay explicit
    """Analytic rectangle/pipe/pair checks in original local metres, no scene queries."""
    failures = []
    placements = report.plan.placements
    if sum(p.species.is_tree for p in placements) < MIN_TREES:
        failures.append("fewer than ten trees: an empty/refusal result is not success")
    for p in placements:
        x, y = case.local(p.x, p.y)
        radius = (
            report.params.planting_radius_m
            if p.species.is_tree
            else report.params.shrub_planting_radius_m
        )
        if min(x, 120 - x, y - 20, 55 - y) < radius - EPSILON_M:
            failures.append(f"{p.placement_id}: planting footprint outside declared soil")
        if y - 20 < (2 if p.species.is_tree else 1) - EPSILON_M:
            failures.append(f"{p.placement_id}: curb clearance")
        if (
            case.curb_shape == "ring"
            and min(x, 120 - x, 55 - y) < (2 if p.species.is_tree else 1) - EPSILON_M
        ):
            failures.append(f"{p.placement_id}: closed curb clearance")
        if 55 - y < (5 if p.species.is_tree else 1.5) - EPSILON_M:
            failures.append(f"{p.placement_id}: building clearance")
        if p.species.is_tree and abs(y - 40) - 0.15 < 2 - EPSILON_M:
            failures.append(f"{p.placement_id}: water-pipe wall clearance")
        if p.verdict.value != "allowed":
            failures.append(f"{p.placement_id}: requires approval on declared complete scene")
    for a, b in itertools.combinations(placements, 2):
        ra = (
            report.params.planting_radius_m
            if a.species.is_tree
            else report.params.shrub_planting_radius_m
        )
        rb = (
            report.params.planting_radius_m
            if b.species.is_tree
            else report.params.shrub_planting_radius_m
        )
        required = ra + rb
        if a.species.is_tree and b.species.is_tree:
            required = max(required, report.params.spacing_m * 0.95)
        if math.hypot(a.x - b.x, a.y - b.y) < required - EPSILON_M:
            failures.append(f"{a.placement_id}/{b.placement_id}: overlapping pits or tree spacing")
    return failures


def compare_variants(report: RunReport) -> tuple[dict[str, object], list[str]]:
    """Check the reported comparison against the selected final plan."""
    portfolio = report.plan.portfolio
    if portfolio is None:
        raise ValueError("portfolio result has no comparison report")
    variants = [v for v in portfolio.variants if v.valid]
    scores = {v.name: v.quality_index for v in variants if v.quality_index is not None}
    if not variants or len(scores) != len(variants):
        raise ValueError("declared site has an unscored valid variant")
    failures = []
    if "baseline" not in scores:
        failures.append("baseline failed on a known feasible complete scene")
    chosen = scores.get(portfolio.chosen, -math.inf)
    if chosen != max(scores.values()):
        failures.append("chosen variant is not the best reported valid quality")
    if report.plan.quality is None or chosen != report.plan.quality.index:
        failures.append("reported portfolio quality differs from the final plan")
    return {
        "chosen": portfolio.chosen,
        "variants": [asdict(v) for v in portfolio.variants],
        "baseline_quality": scores.get("baseline"),
        "gain_over_baseline": chosen - scores.get("baseline", chosen),
    }, failures


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="0 runs the full 72-case product")
    parser.add_argument(
        "--solver", choices=("mixed", "greedy", "milp", "portfolio"), default="mixed"
    )
    parser.add_argument("--work-dir", type=Path, default=OUTPUT)
    parser.add_argument("--curb-shape", choices=("line", "ring"), default="line")
    parser.add_argument(
        "--check-existing",
        action="store_true",
        help="Check equivalence in --output without rerunning",
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "docs/research/verified-pipeline/universal_dxf.json"
    )
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be zero or positive")
    return args


def check_representations(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare units, insertion and naming, holding physical pose and solver fixed."""
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        if row["ok"]:
            key = tuple(row[k] for k in ("material", "angle", "shift", "mirror", "solver"))
            key += (row.get("curb_shape", "line"),)
            groups.setdefault(key, []).append(row)
    summary = []
    for key, group in groups.items():
        values = [r["quality_index"] for r in group]
        spread = max(values) - min(values)
        summary.append(
            {
                "material_pose_solver": key,
                "representations": len(group),
                "quality_spread": spread,
                "tolerance": QUALITY_EQUIVALENCE_TOLERANCE,
                "ok": spread <= QUALITY_EQUIVALENCE_TOLERANCE,
            }
        )
    return summary


def run_matrix(args: argparse.Namespace) -> None:
    args.work_dir.mkdir(parents=True, exist_ok=True)
    container = build_container(
        Settings(config_dir=ROOT / "config", runs_dir=args.work_dir / "runs")
    )
    product = itertools.product(
        ("area", "label"),
        ((6, 1.0), (4, 0.001), (2, 0.3048)),
        ((0, 0, 1), (37, 1_000_000, 1), (113, 100_000, -1)),
        (False, True),
        (False, True),
    )
    rows = []
    for number, (material, units, pose, nested, single_layer) in enumerate(product):
        if args.limit and number >= args.limit:
            break
        case = Case(
            material,
            *units,
            *pose,
            nested,
            single_layer,
            "R2000" if number % 2 else "R2018",
            args.curb_shape,
        )
        name = f"case-{number:03d}"
        work = args.work_dir / name
        work.mkdir(exist_ok=True)
        source = work / "source.dxf"
        roles = drawing(source, case)
        begin = time.perf_counter()
        row = {"case": name, **asdict(case), "ok": False}
        try:
            params = container.profiles.load(
                "strict", {"placement_solver": "greedy", "max_rejections": 30}
            )
            try:
                container.use_case.execute(
                    PlanRequest(name, source, work / "unreviewed", "strict", params)
                )
            except ClassificationError:
                row["unreviewed_rejected"] = True
            else:
                raise ValueError("unknown source did not stop strict classification")
            scene = EzdxfSceneReader().read(source)
            if len(scene.features) != len(roles):
                raise ValueError("synthetic source lost or duplicated a geometry entity")  # noqa: TRY301 - retain failure and continue matrix
            overrides = {
                "semantic_source_sha256": scene.source_sha256,
                "feature_classes": {
                    str(f.ref): role for f, role in zip(scene.features, roles, strict=True)
                },
                "label_roles": {str(t.ref): "soil" for t in scene.labels if t.text == "M-017"},
                "placement_solver": ("portfolio" if number % 12 == 0 else "greedy")
                if args.solver == "mixed"
                else args.solver,
                "max_rejections": 30,
            }
            (work / "review.json").write_text(json.dumps(overrides, indent=2) + "\n")
            params = container.profiles.load("strict", overrides)
            report = container.use_case.execute(
                PlanRequest(name, source, work / "reviewed", "strict", params)
            )
            container.artifacts.save(work / "reviewed", report)
            failures = oracle(report, case)
            if params.placement_solver == "portfolio":
                comparison, comparison_failures = compare_variants(report)
                row.update(comparison)
                failures.extend(comparison_failures)
            row.update(
                ok=not failures
                and report.integrity.ok
                and bool(report.validation and report.validation.ok)
                and bool(report.export_validation and report.export_validation.ok),
                source_sha256=scene.source_sha256,
                features=len(scene.features),
                labels=len(scene.labels),
                trees=sum(p.species.is_tree for p in report.plan.placements),
                shrubs=sum(p.species.is_shrub for p in report.plan.placements),
                analytic_oracle_failures=failures,
                validation_ok=bool(report.validation and report.validation.ok),
                source_preserved=report.integrity.ok,
                saved_dxf_matches=bool(report.export_validation and report.export_validation.ok),
                solver=params.placement_solver,
                quality_index=report.plan.quality.index if report.plan.quality else None,
                quality_terms=[asdict(t) for t in report.plan.quality.terms]
                if report.plan.quality
                else [],
            )
        except Exception as error:  # noqa: BLE001 - finish matrix and retain every failure
            row["error"] = f"{type(error).__name__}: {error}"
        row["seconds"] = round(time.perf_counter() - begin, 4)
        rows.append(row)
        print(row, flush=True)
    checks = check_representations(rows)
    args.output.write_text(
        json.dumps(
            {
                "scope": "Declared synthetic truth and exact human-equivalent assignments; "
                "tests transfer of geometry/constraints/export, not automatic recognition or "
                "globally optimal aesthetics. "
                "R2000 is paired with single-layer inputs; R2018 with opaque multiple layers.",
                "solver_mode": args.solver,
                "representation_comparison": checks,
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print({"runs": len(rows), "passed": sum(bool(r["ok"]) for r in rows)}, flush=True)
    if any(not row["ok"] for row in rows) or any(not check["ok"] for check in checks):
        raise SystemExit(1)


def main() -> None:
    args = arguments()
    if args.check_existing:
        rows = json.loads(args.output.read_text())["rows"]
        checks = check_representations(rows)
        print(json.dumps(checks, indent=2))
        if not checks or any(not c["ok"] for c in checks) or any(not r["ok"] for r in rows):
            raise SystemExit(1)
    else:
        run_matrix(args)


if __name__ == "__main__":
    main()
