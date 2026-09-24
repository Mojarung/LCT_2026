"""Compare complete plans on the same synthetic street with one multipart tree sign."""

# ruff: noqa: INP001, T201 - standalone experiment prints a JSON record

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import platform
import resource
import time
from pathlib import Path

import ezdxf

from green.application.errors import InputError
from green.application.use_case import PlanRequest
from green.bootstrap.container import build_container
from green.bootstrap.settings import Settings


def make_fixture(path: Path) -> None:
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 6
    for layer in (
        "Граница заказа",
        "Бортовой камень",
        "Граница улицы",
        "Леса и газоны",
        "Водопровод",
        "Здания",
        "!!!_1. Дендра_сохранить",
    ):
        doc.layers.add(layer)
    msp = doc.modelspace()
    msp.add_lwpolyline(
        [(0, 0), (120, 0), (120, 60), (0, 60)],
        close=True,
        dxfattribs={"layer": "Граница заказа"},
    )
    for x in range(120):
        msp.add_line((x, 20), (x + 0.7, 20), dxfattribs={"layer": "Бортовой камень"})
    msp.add_lwpolyline(
        [(0, 20), (120, 20), (120, 55), (0, 55)],
        close=True,
        dxfattribs={"layer": "Леса и газоны"},
    )
    msp.add_text("А", height=2.5, dxfattribs={"layer": "Граница улицы"}).set_placement(
        (60, 10)
    )
    msp.add_text("ГАЗОН", height=2.5, dxfattribs={"layer": "Леса и газоны"}).set_placement(
        (60, 30)
    )
    msp.add_line((0, 40), (120, 40), dxfattribs={"layer": "Водопровод"})
    msp.add_text("d=300ст.", height=2.5, dxfattribs={"layer": "Водопровод"}).set_placement(
        (60, 40.5)
    )
    msp.add_lwpolyline(
        [(0, 55), (120, 55), (120, 60), (0, 60)],
        close=True,
        dxfattribs={"layer": "Здания"},
    )
    sign = doc.blocks.new("TREE_SIGN")
    for radius in (0.25, 0.4, 0.6, 0.75, 0.9, 1.0, 1.1, 1.2):
        sign.add_circle((0, 0), radius)
    for angle in range(4):
        sign.add_line((-0.5 + angle * 0.1, 0), (0.5 + angle * 0.1, 0))
    msp.add_blockref(
        "TREE_SIGN", (60, 28), dxfattribs={"layer": "!!!_1. Дендра_сохранить"}
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--make-fixture", action="store_true")
    args = parser.parse_args()
    if args.make_fixture:
        make_fixture(args.source)
    source_hash = hashlib.sha256(args.source.read_bytes()).hexdigest()
    started = time.perf_counter()
    container = build_container(Settings(config_dir=args.config, runs_dir=args.out / "runs"))
    params = container.profiles.load("strict", {"max_rejections": 50, "placement_solver": "greedy"})
    result: dict[str, object]
    try:
        report = container.use_case.execute(
            PlanRequest("tree-symbol-study", args.source, args.out, "strict", params)
        )
    except InputError as error:
        result = {"status": "rejected", "error": str(error)}
    else:
        placements = [
            {"x": p.x, "y": p.y, "species": p.species.code}
            for p in report.plan.placements
        ]
        args.out.mkdir(parents=True, exist_ok=True)
        placements_path = args.out / "placements.json"
        placements_path.write_text(json.dumps(placements, ensure_ascii=False, indent=2) + "\n")
        result = {
            "status": "completed",
            "existing_tree_features": report.class_counts.get("existing_tree", 0),
            "summary": report.summary(),
            "quality_index": report.plan.quality.index if report.plan.quality else None,
            "species": dict(report.plan.assortment_summary.counts)
            if report.plan.assortment_summary
            else None,
            "placements_sha256": hashlib.sha256(placements_path.read_bytes()).hexdigest(),
        }
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result.update(
        source_sha256=source_hash,
        config_sha256=hashlib.sha256((args.config / "layer_map.yaml").read_bytes()).hexdigest(),
        reader_module=inspect.getfile(container.reader.__class__),
        duration_s=round(time.perf_counter() - started, 3),
        peak_rss_mb=round(
            peak / (1024 * 1024) if platform.system() == "Darwin" else peak / 1024, 2
        ),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
