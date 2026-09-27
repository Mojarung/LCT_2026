"""Frozen, controlled perturbations of a known scene; no tuning on results."""

# ruff: noqa: INP001, T201, S603 - standalone subprocess experiment
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import ezdxf
import similar_layouts as layouts
from ezdxf.math import Matrix44
from shapely import affinity
from shapely.geometry import LineString, MultiPoint, box, mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ("baseline", {}),
    ("repeat", {}),
    ("reverse_entities", {}),
    ("translated", {}),
    ("millimetres", {}),
    ("rotation_only", {}),
    ("nested_only", {}),
    ("overlap_pavement", {}),
    ("dense_water", {}),
    ("dense_trees", {}),
    ("no_boundary", {}),
    ("no_utilities", {}),
    ("missing_xref", {}),
    ("unitless", {}),
    ("unitless_explicit", {"drawing_unit": "m"}),
    ("unknown_water", {}),
    ("unknown_water_review", {"assume_unknown_geometry": False}),
    ("open_lawn", {}),
    ("label_only_lawn", {}),
    ("greedy", {"placement_solver": "greedy"}),
    ("milp", {"placement_solver": "milp"}),
]


def prepare(out: Path) -> list:  # noqa: C901,PLR0912,PLR0915 - explicit experimental cases
    inputs = []
    for name, overrides in CASES:
        source = out / f"{name}.dxf"
        oracle = layouts.make_case(
            source,
            12,
            crossing=False,
            scale=1000 if name == "millimetres" else 1,
            angle=37 if name == "rotation_only" else 0,
            nested=name == "nested_only",
        )
        doc = ezdxf.readfile(source)
        msp = doc.modelspace()
        if name == "reverse_entities":
            entities = list(msp)
            for e in entities:
                msp.unlink_entity(e)
            for e in reversed(entities):
                msp.add_entity(e)
        if name == "translated":
            for e in msp:
                e.transform(Matrix44.translate(12000, -9000, 0))
            oracle = {
                k: mapping(affinity.translate(shape(v), 12000, -9000)) for k, v in oracle.items()
            }
        if name == "overlap_pavement":
            patch = box(32027, 74005, 32035, 74017)
            msp.add_lwpolyline(
                list(patch.exterior.coords), close=True, dxfattribs={"layer": "Тротуар"}
            )
            oracle["soil"] = mapping(shape(oracle["soil"]).difference(patch))
        if name == "dense_water":
            water = [shape(oracle["water"])]
            for x in range(2, 64, 4):
                line = LineString([(32000 + x, 74000), (32000 + x, 74022)])
                msp.add_line(
                    line.coords[0], line.coords[1], dxfattribs={"layer": "Сущ_Сети_Водопровод"}
                )
                water.append(line)
            oracle["water"] = mapping(unary_union(water))
        if name == "dense_trees":
            trees = [shape(oracle["tree"])]
            for x in range(4, 64, 8):
                for y in (8, 14):
                    msp.add_blockref(
                        "DEREVO",
                        (32000 + x, 74000 + y),
                        dxfattribs={"layer": "Топо_Отдельно стоящее дерево"},
                    )
                    trees.append(__import__("shapely").Point(32000 + x, 74000 + y))
            oracle["tree"] = mapping(MultiPoint(trees))
        if name in ("no_boundary", "no_utilities"):
            layer = "Граница работ" if name == "no_boundary" else "Сущ_Сети_Водопровод"
            for e in list(msp):
                if e.dxf.layer == layer:
                    msp.delete_entity(e)
        if name == "missing_xref":
            doc.add_xref_def("not_supplied.dxf", "MISSING_SURVEY")
            msp.add_blockref("MISSING_SURVEY", (32000, 74000))
        if name.startswith("unitless"):
            doc.units = 0
        if name.startswith("unknown_water"):
            doc.layers.new("CUSTOM_utility_2026")
            for e in msp:
                if e.dxf.layer == "Сущ_Сети_Водопровод":
                    e.dxf.layer = "CUSTOM_utility_2026"
        if name in ("open_lawn", "label_only_lawn"):
            for e in list(msp):
                if e.dxf.layer == "Топо_Леса и газоны":
                    if name == "open_lawn":
                        e.closed = False
                    else:
                        msp.delete_entity(e)
            msp.add_text(
                "ГАЗОН", dxfattribs={"layer": "Топо_Леса и газоны", "height": 1}
            ).set_placement((32032, 74011))
        doc.saveas(source)
        source.with_suffix(".oracle.json").write_text(json.dumps(oracle, indent=2) + "\n")
        inputs.append((name, overrides, source, oracle))
    (out / "selection.json").write_text(json.dumps(CASES, ensure_ascii=False, indent=2) + "\n")
    return inputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = prepare(out)
    rows = []
    for name, overrides, source, oracle in inputs:
        work = out / name
        work.mkdir(exist_ok=True)
        command = [
            sys.executable,
            str(ROOT / "tools/research/cross_branch_eval.py"),
            "--root",
            str(ROOT),
            "--source",
            str(source),
            "--out",
            str(work),
            "--variant",
            name,
            "--overrides",
            json.dumps(overrides),
        ]
        with (work / "console.log").open("w") as log:
            subprocess.run(
                command,
                cwd=ROOT,
                env=dict(os.environ, PYTHONPATH=str(ROOT / "src")),
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=180,
                check=True,
            )
        r = json.loads((work / "result.json").read_text())
        row = {
            k: r.get(k)
            for k in (
                "variant",
                "status",
                "error",
                "elapsed_s",
                "peak_rss_mib_macos",
                "quality_index",
            )
        }
        row.update(layouts.inspect(r, oracle))
        row["warnings"] = r.get("summary", {}).get("warnings", [])
        row["checks"] = (
            {
                k: json.loads((work / "run" / f"{k}.json").read_text())["ok"]
                for k in ("verify", "validation", "export_validation")
            }
            if r["status"] == "complete"
            else {}
        )
        rows.append(row)
        (out / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")
        print(
            json.dumps(
                {k: v for k, v in row.items() if k not in ("warnings", "error")}, ensure_ascii=False
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
