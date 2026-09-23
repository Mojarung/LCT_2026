"""Compare selectors through parsing, species assignment, validation and DXF round-trip.

Synthetic scenes have deliberately declared semantics; they do not measure semantic
recognition accuracy. The tracked demo is a flattened excerpt, not untouched field data.
"""
# ruff: noqa: INP001, T201 - standalone experiment driver with live progress

from __future__ import annotations

import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf

from green.application.errors import InputError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings

if TYPE_CHECKING:
    from collections.abc import Sequence

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "out/placement-benchmark"


def _scene(path: Path, name: str, angle: float) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    model = doc.modelspace()

    def points(vertices: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
        return [
            (
                100_000 + x * math.cos(angle) - y * math.sin(angle),
                200_000 + x * math.sin(angle) + y * math.cos(angle),
            )
            for x, y in vertices
        ]

    def polygon(layer: str, vertices: Sequence[tuple[float, float]]) -> None:
        if layer not in doc.layers:
            doc.layers.add(layer)
        model.add_lwpolyline(points(vertices), close=True, dxfattribs={"layer": layer})

    def line(layer: str, start: tuple[float, float], end: tuple[float, float]) -> None:
        if layer not in doc.layers:
            doc.layers.add(layer)
        a, b = points((start, end))
        model.add_line(a, b, dxfattribs={"layer": layer})

    polygon("Граница работ", [(0, 0), (100, 0), (100, 50), (0, 50)])
    polygon("Газон", [(0, 10), (100, 10), (100, 45), (0, 45)])
    polygon("Проезжая часть", [(0, 0), (100, 0), (100, 10), (0, 10)])
    polygon("Здания", [(0, 45), (100, 45), (100, 50), (0, 50)])
    line("Бортовой камень", (0, 10), (100, 10))
    line("Водопровод", (0, 28), (100, 28))
    if name == "crossing":
        line("Кабель связи", (40, 10), (65, 45))
        line("Бортовой камень", (20, 10), (55, 40))
        polygon("Тротуар", [(40, 10), (45, 10), (45, 45), (40, 45)])
    elif name == "courtyard":
        polygon("Тротуар", [(20, 18), (75, 18), (75, 23), (20, 23)])
        polygon("Здания", [(50, 32), (70, 32), (70, 42), (50, 42)])
        line("Бортовой камень", (20, 23), (75, 23))
    doc.saveas(path)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cases = []
    for name in ("strip", "crossing", "courtyard"):
        for angle in (0.0, 0.37, 0.83):
            case = f"{name}-{angle}"
            path = OUTPUT / f"{case}.dxf"
            _scene(path, name, angle)
            cases.append((case, path, "synthetic"))
    cases.append(
        (
            "berzarina-fragment",
            ROOT / "src/green/infrastructure/cad/samples/berzarina_fragment.dxf",
            "flattened_demo",
        )
    )
    container = build_container(Settings(config_dir=ROOT / "config", runs_dir=OUTPUT / "runs"))
    rows = []
    for name, source, kind in cases:
        for solver in ("greedy", "milp"):
            begin = time.perf_counter()
            params = container.profiles.load(
                "strict", {"placement_solver": solver, "placement_time_limit_s": 5.0}
            )
            row = {"case": name, "kind": kind, "solver": solver}
            try:
                report = container.use_case.execute(
                    PlanRequest(name, source, OUTPUT / name / solver, "strict", params)
                )
            except InputError as error:
                row.update(ok=False, error=str(error))
            else:
                container.artifacts.save(OUTPUT / name / solver, report)
                plan = report.plan
                row.update(
                    ok=report.validation.ok and report.integrity.ok and report.export_validation.ok,
                    source_sha256=report.source_sha256,
                    trees=sum(p.species.is_tree for p in plan.placements),
                    shrubs=sum(p.species.is_shrub for p in plan.placements),
                    needs_approval=plan.approval_count,
                    quality_index=plan.quality.index if plan.quality else None,
                    quality_terms=[asdict(term) for term in plan.quality.terms]
                    if plan.quality
                    else [],
                    selection=asdict(plan.selection) if plan.selection else None,
                    no_species=plan.assortment_summary.no_species
                    if plan.assortment_summary
                    else None,
                    stages_ms={stage.stage: stage.ms for stage in report.timings},
                )
            row["seconds"] = round(time.perf_counter() - begin, 4)
            rows.append(row)
            print(
                {
                    k: v
                    for k, v in row.items()
                    if k not in {"quality_terms", "selection", "stages_ms"}
                },
                flush=True,
            )
    target = ROOT / "docs/research/verified-pipeline/placement_comparison.json"
    target.write_text(
        json.dumps(
            {
                "scope": (
                    "Declared synthetic semantics and a flattened demo; "
                    "no recognition accuracy or global aesthetic optimum claim."
                ),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    if any(not row["ok"] for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
