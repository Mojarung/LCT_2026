"""Freeze new geometric holdouts before planning; check against authored geometry.

Synthetic zones are not independently surveyed real streets. Run with --out DIR.
The four shape families include holes, islands, concave edges and oblique boundaries.
"""

# ruff: noqa: INP001,T201 - standalone research runner
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box, mapping
from similar_layouts import inspect

if TYPE_CHECKING:
    from numpy.random import Generator
    from shapely.geometry.base import BaseGeometry

ROOT = Path(__file__).resolve().parents[2]
FAMILIES = 4


def make_case(target: Path, index: int, rng: Generator) -> dict:
    """Define the oracle first, then encode it as DXF using explicit material hatches."""
    width, height = float(rng.uniform(55, 95)), float(rng.uniform(24, 42))
    boundary = box(0, 0, width, height)
    soil = box(3, 6, width - 3, height - 3)
    family = index % FAMILIES
    if family == 0:
        soil = soil.difference(box(width * 0.4, 11, width * 0.6, height - 7))
    elif family == 1:
        soil = soil.difference(box(width * 0.48, 0, width * 0.53, height))
    elif family == 2:  # noqa: PLR2004 - shape family
        soil = soil.difference(box(width * 0.65, height * 0.55, width, height))
    else:
        soil = soil.intersection(
            Polygon(
                [
                    (3, 6),
                    (width - 3, 6),
                    (width - 9, height - 3),
                    (width * 0.35, height - 6),
                    (3, height - 3),
                ]
            )
        )
    water = LineString([(width * 0.27, 0), (width * 0.27, height)])
    curb = LineString([(0, 4), (width, 4)])
    tree = Point(width * 0.75, 9)
    angle, dx, dy = (
        float(rng.uniform(0, 180)),
        float(rng.uniform(-90000, 90000)),
        float(rng.uniform(-90000, 90000)),
    )

    def world(geometry: BaseGeometry) -> BaseGeometry:
        return affinity.translate(affinity.rotate(geometry, angle, origin=(0, 0)), dx, dy)

    geometry = {
        key: world(value)
        for key, value in {
            "soil": soil,
            "boundary": boundary,
            "water": water,
            "curb": curb,
            "tree": tree,
        }.items()
    }
    doc = ezdxf.new("R2018")
    doc.units = 6
    space = doc.modelspace()
    for area, layer in ((geometry["soil"], "Газон"), (world(boundary.difference(soil)), "Тротуар")):
        doc.layers.new(layer)
        for polygon in shapely.get_parts(area):
            hatch = space.add_hatch(color=3, dxfattribs={"layer": layer})
            hatch.paths.add_polyline_path(list(polygon.exterior.coords), is_closed=True, flags=1)
            for hole in polygon.interiors:
                hatch.paths.add_polyline_path(list(hole.coords), is_closed=True, flags=0)
    doc.layers.new("Граница работ")
    space.add_lwpolyline(
        list(geometry["boundary"].exterior.coords),
        close=True,
        dxfattribs={"layer": "Граница работ"},
    )
    for key, layer in (("water", "Водопровод"), ("curb", "Бортовой камень")):
        doc.layers.new(layer)
        start, end = geometry[key].coords
        space.add_line(start, end, dxfattribs={"layer": layer})
    doc.layers.new("Отдельно стоящее дерево")
    point = geometry["tree"]
    space.add_circle((point.x, point.y), 0.15, dxfattribs={"layer": "Отдельно стоящее дерево"})
    doc.saveas(target)
    return {
        "name": target.stem,
        "family": family,
        "source": str(target),
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "oracle": {key: mapping(value) for key, value in geometry.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260928)
    parser.add_argument("--count", type=int, default=16)
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count must be positive")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    selection = out / "selection.json"
    if selection.exists():
        cases = json.loads(selection.read_text())
    else:
        rng = np.random.default_rng(args.seed)
        cases = [make_case(out / f"zone-{i:02}.dxf", i, rng) for i in range(args.count)]
        selection.write_text(json.dumps(cases, indent=2) + "\n")
    rows = []
    for case in cases:
        source = Path(case["source"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != case["sha256"]:
            raise ValueError(f"Frozen source changed: {source}")
        work = out / case["name"]
        work.mkdir(exist_ok=True)
        with (work / "console.log").open("w") as log:
            subprocess.run(  # noqa: S603 - fixed local executable and argument vector
                [
                    sys.executable,
                    str(ROOT / "tools/research/cross_branch_eval.py"),
                    "--root",
                    str(ROOT),
                    "--source",
                    str(source),
                    "--out",
                    str(work),
                    "--variant",
                    case["name"],
                    "--overrides",
                    '{"infer_unknown":false}',
                ],
                env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=180,
                check=True,
            )
        result = json.loads((work / "result.json").read_text())
        row = {key: result.get(key) for key in ("status", "error", "elapsed_s", "quality_index")}
        row.update(
            name=case["name"],
            family=case["family"],
            source_sha256=case["sha256"],
            **inspect(result, case["oracle"]),
        )
        row["checks"] = {
            key: result.get("summary", {}).get(key)
            for key in (
                "plan_valid",
                "integrity_ok",
                "export_matches_plan",
                "surface_unconfirmed_placements",
            )
        }
        rows.append(row)
        (out / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)
    failed = any(
        row["status"] != "complete"
        or row["oracle_violations"]
        or row["trees"] + row["shrubs"] == 0
        or not all(
            row["checks"][key] is True
            for key in ("plan_valid", "integrity_ok", "export_matches_plan")
        )
        or row["checks"]["surface_unconfirmed_placements"] != 0
        for row in rows
    )
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
