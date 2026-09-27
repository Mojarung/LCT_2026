"""Fresh controlled layouts using the pilot's legend; geometry oracle is authored first.

Run: uv run python tools/research/similar_layouts.py --out out/similar-layouts
No street-specific classifier changes. Synthetic cases are not real unseen streets.
"""

# ruff: noqa: INP001,T201 - standalone experiment
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import ezdxf
from shapely import affinity
from shapely.geometry import LineString, Point, box, mapping, shape

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

ROOT = Path(__file__).resolve().parents[2]
MILLIMETRES = 1000
CASES = [
    ("narrow_2.2", 2.2, False, 1, 0, False),
    ("strip_3.6", 3.6, False, 1, 0, False),
    ("wide_12", 12.0, False, 1, 0, False),
    ("crossing_24", 24.0, True, 1, 0, False),
    ("islands_12", 12.0, True, 1, 0, False),
    ("wide_mm", 12.0, False, 1000, 0, False),
    ("wide_rotated", 12.0, False, 1, 37, True),
    ("wide_mm_rotated", 12.0, False, 1000, 37, True),
]


def make_case(  # noqa: PLR0913 - explicit controlled factors
    target: Path, width: float, *, crossing: bool, scale: int, angle: float, nested: bool
) -> dict:
    """Independent scene definition in metres, before writing or parsing DXF."""
    boundary = box(0, 0, 64, width + 10)
    grass = box(0, 5, 64, width + 5)
    road = box(0, 0, 64, 5)
    upper_pavement = box(0, width + 5, 64, width + 10)
    crossing_area = box(29, 5, 35, width + 5) if crossing else None
    soil = grass.difference(crossing_area) if crossing_area is not None else grass
    water = LineString([(19, 0), (19, width + 10)])
    curb = LineString([(0, 5), (64, 5)])
    tree = Point(47, 5 + width / 2)

    def world(geometry: BaseGeometry) -> BaseGeometry:
        return affinity.translate(affinity.rotate(geometry, angle, origin=(0, 0)), 32000, 74000)

    doc = ezdxf.new("R2018")
    doc.units = 4 if scale == MILLIMETRES else 6
    space = doc.blocks.new("msdElementType_site") if nested else doc.modelspace()

    def polygon(geometry: BaseGeometry, layer: str) -> None:
        if layer not in doc.layers:
            doc.layers.new(layer)
        geometry = geometry if nested else world(geometry)
        space.add_lwpolyline(
            [(x * scale, y * scale) for x, y in geometry.exterior.coords],
            close=True,
            dxfattribs={"layer": layer},
        )

    polygon(boundary, "Граница работ")
    polygon(grass, "Топо_Леса и газоны")
    polygon(road, "Проезжая часть")
    polygon(upper_pavement, "Тротуар")
    if crossing_area is not None:
        polygon(crossing_area, "Тротуар")
    for geometry, layer in [(curb, "Топо_Бортовой камень"), (water, "Сущ_Сети_Водопровод")]:
        doc.layers.new(layer)
        line = geometry if nested else world(geometry)
        first, last = line.coords
        space.add_line(
            tuple(v * scale for v in first),
            tuple(v * scale for v in last),
            dxfattribs={"layer": layer},
        )
    symbol = doc.blocks.new("DEREVO")
    symbol.add_circle((0, 0), 0.15 * scale)
    symbol.add_ellipse((0, 0), major_axis=(0.7 * scale, 0), ratio=0.6)
    doc.layers.new("Топо_Отдельно стоящее дерево")
    origin = tree if nested else world(tree)
    space.add_blockref(
        "DEREVO",
        (origin.x * scale, origin.y * scale),
        dxfattribs={"layer": "Топо_Отдельно стоящее дерево"},
    )
    if nested:
        doc.modelspace().add_blockref(
            space.name, (32000 * scale, 74000 * scale), dxfattribs={"rotation": angle}
        )
    doc.saveas(target)
    oracle = {
        name: mapping(world(g))
        for name, g in {
            "soil": soil,
            "boundary": boundary,
            "water": water,
            "curb": curb,
            "tree": tree,
        }.items()
    }
    target.with_suffix(".oracle.json").write_text(json.dumps(oracle, indent=2) + "\n")
    return oracle


def inspect(result: dict, oracle: dict) -> dict:
    """Use authored geometry and direct distances, not the classifier/validator."""
    geometry = {name: shape(value) for name, value in oracle.items()}
    plants = result.get("placements", [])
    violations = []
    trees = []
    for i, plant in enumerate(plants):
        p = Point(plant["x"], plant["y"])
        radius = 1.24 if plant["tree"] else 0.5
        for name in ["soil", "boundary"]:
            area = geometry[name]
            if not area.covers(p) or p.distance(area.boundary) < radius - 0.002:
                violations.append([i, name])
        if plant["tree"]:
            trees.append(p)
            for name, minimum in [("water", 2), ("curb", 2), ("tree", 5)]:
                if p.distance(geometry[name]) < minimum - 0.002:
                    violations.append([i, name])
        elif p.distance(geometry["tree"]) < 1 - 0.002:
            violations.append([i, "existing_tree"])
    distances = [a.distance(b) for i, a in enumerate(trees) for b in trees[i + 1 :]]
    if any(d < 5 - 0.002 for d in distances):
        violations.append(["pairs", "tree_spacing"])
    return {
        "trees": len(trees),
        "shrubs": sum(p["shrub"] for p in plants),
        "oracle_violations": violations,
        "tree_step_min_m": min(distances, default=None),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    # All cases and ground truth are fixed before the first algorithm result.
    sources = []
    for name, width, crossing, scale, angle, nested in CASES:
        source = out / f"{name}.dxf"
        oracle = make_case(
            source, width, crossing=crossing, scale=scale, angle=angle, nested=nested
        )
        sources.append((name, source, oracle))
    results = []
    for name, source, oracle in sources:
        run = out / name
        run.mkdir(exist_ok=True)
        command = [
            sys.executable,
            str(ROOT / "tools/research/cross_branch_eval.py"),
            "--root",
            str(ROOT),
            "--source",
            str(source),
            "--out",
            str(run),
            "--variant",
            name,
        ]
        with (run / "console.log").open("w") as log:
            subprocess.run(  # noqa: S603 - fixed local harness and generated local DXF
                command,
                cwd=ROOT,
                env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=180,
                check=True,
            )
        result = json.loads((run / "result.json").read_text())
        row = {
            "case": name,
            "status": result["status"],
            "error": result.get("error"),
            **inspect(result, oracle),
        }
        if result["status"] == "complete":
            row["checks"] = {
                kind: json.loads((run / "run" / f"{kind}.json").read_text())["ok"]
                for kind in ["verify", "validation", "export_validation"]
            }
        results.append(row)
        (out / "summary.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
