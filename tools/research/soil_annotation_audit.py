"""Score saved plans against separately authored, explicitly uncertain surface polygons.

The annotations are visual interpretations, not field-verified ground truth.
Run with --annotations PATH --runs PATH --out PATH. No model fitting or code edits.
"""

# ruff: noqa: INP001,T201,PLC0415 - standalone audit; scorer imports no application code
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import shapely
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

MIN_PAVED_OVERLAP_M2 = 0.01


def annotation_areas(case: dict) -> dict:
    """World coordinates; broad pavement envelopes exclude explicitly traced lawns."""
    areas = {}
    for category in ("soil", "paved"):
        polygons = [Polygon(row["vertices"]) for row in case[category]]
        for row, polygon in zip(case[category], polygons, strict=True):
            if not polygon.is_valid:
                raise ValueError(f"Invalid annotation: {case['case']}/{row['name']}")
        areas[category] = affinity.translate(unary_union(polygons), *case["origin"])
    areas["paved"] = areas["paved"].difference(areas["soil"])
    return areas


def score(plants: list, areas: dict, band: float) -> dict:
    soil = areas["soil"].buffer(-band)
    paved = areas["paved"].buffer(-band)
    rows = []
    for index, plant in enumerate(plants):
        centre = Point(plant["x"], plant["y"])
        radius = 1.24 if plant["tree"] else 0.5
        pit = centre.buffer(radius, quad_segs=64)
        paved_overlap = pit.intersection(paved).area
        if soil.covers(pit):
            status = "supported_soil"
        elif paved_overlap > MIN_PAVED_OVERLAP_M2:
            status = "paved_conflict"
        else:
            status = "uncertain"
        rows.append(
            {
                "index": index,
                "x": plant["x"],
                "y": plant["y"],
                "radius_m": radius,
                "status": status,
                "paved_overlap_m2": paved_overlap,
                "soil_pit_fraction": pit.intersection(soil).area / pit.area,
            }
        )
    counts = {
        status: sum(r["status"] == status for r in rows)
        for status in ("supported_soil", "paved_conflict", "uncertain")
    }
    return {"band_m": band, "count": len(plants), **counts, "placements": rows}


def run(annotations: Path, runs: Path, out: Path) -> None:  # noqa: C901,PLR0915 - linear research audit
    import matplotlib as mpl

    mpl.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Circle

    from green.application.classification import classify_scene
    from green.application.constraints import work_boundary
    from green.application.surfaces import Material, build_surface_map
    from green.bootstrap.container import build_container
    from green.bootstrap.settings import Settings

    out.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    data = json.loads(annotations.read_text())
    report = {
        "annotation_sha256": hashlib.sha256(annotations.read_bytes()).hexdigest(),
        "method": data["annotation_method"],
        "cases": [],
    }
    for case in data["cases"]:
        source = Path(case["source"])
        if hashlib.sha256(source.read_bytes()).hexdigest() != case["source_sha256"]:
            raise ValueError(f"Source changed: {source}")
        areas = annotation_areas(case)
        work = runs / case["case"]
        result_path = work / "plan/result.json"
        result = json.loads(result_path.read_text())
        plants = result["placements"]
        scores = [score(plants, areas, band) for band in (0.1, 0.25, 0.5)]
        primary = scores[1]
        # The production map is only the prediction being evaluated.
        container = build_container(
            Settings(config_dir=root / "config", runs_dir=out / "runs", converter="none")
        )
        params = container.profiles.load("strict", {})
        scene = container.reader.read(work / "merged.dxf")
        scene, _ = classify_scene(scene, container.layers.load(), params)
        boundary = work_boundary(scene.features)
        surface = build_surface_map(
            scene.features,
            scene.labels,
            boundary,
            params.surface_cell_m,
            inference_mode=params.surface_inference_mode,
        )
        import numpy as np

        ys, xs = np.where(surface.grid == Material.SOIL)
        x = surface.origin[0] + xs * surface.cell
        y = surface.origin[1] + ys * surface.cell
        predicted = shapely.union_all(
            shapely.box(x, y, x + surface.cell, y + surface.cell)
        ).intersection(boundary)
        soil_core = areas["soil"].buffer(-0.25).intersection(boundary)
        paved_core = areas["paved"].buffer(-0.25).intersection(boundary)
        correct = predicted.intersection(soil_core).area
        wrong = predicted.intersection(paved_core).area
        area_metrics = {
            "predicted_soil_m2": predicted.area,
            "supported_soil_m2": correct,
            "paved_conflict_m2": wrong,
            "unassessed_or_boundary_m2": predicted.area - correct - wrong,
            "assessed_soil_recall": correct / soil_core.area if soil_core.area else None,
            "precision_on_assessed_area": correct / (correct + wrong) if correct + wrong else None,
        }
        row = {
            "case": case["case"],
            "result_sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
            "primary": primary,
            "sensitivity": [{k: v for k, v in s.items() if k != "placements"} for s in scores],
            "area_metrics": area_metrics,
        }
        report["cases"].append(row)
        raw = json.loads((annotations.parent / f"{case['case']}-raw-geometry.json").read_text())
        fig, axes = plt.subplots(1, 2, figsize=(14, 12), layout="constrained")
        for axis, overlay in zip(axes, (False, True), strict=True):
            for category, color in [("paved", "#e9c9c9"), ("soil", "#c9e7c5")]:
                for part in shapely.get_parts(areas[category]):
                    if part.geom_type == "Polygon":
                        axis.fill(*part.exterior.xy, color=color, alpha=0.6)
                        for ring in part.interiors:
                            axis.fill(*ring.xy, color="white")
            for entity in raw["entities"]:
                if entity.get("points"):
                    points = np.array(entity["points"]) + case["origin"]
                    axis.plot(points[:, 0], points[:, 1], color=".45", linewidth=0.5)
            if overlay:
                colors = {
                    "supported_soil": "#117733",
                    "paved_conflict": "#cc3311",
                    "uncertain": "#dd9900",
                }
                for p in primary["placements"]:
                    axis.add_patch(
                        Circle(
                            (p["x"], p["y"]), p["radius_m"], color=colors[p["status"]], alpha=0.8
                        )
                    )
                    if p["status"] != "supported_soil":
                        axis.annotate(str(p["index"]), (p["x"], p["y"]), fontsize=8)
            xmin, ymin, xmax, ymax = boundary.bounds
            axis.set_xlim(xmin - 1, xmax + 1)
            axis.set_ylim(ymin - 1, ymax + 1)
            axis.set_aspect("equal")
            axis.ticklabel_format(useOffset=False)
            axis.tick_params(labelsize=7)
            axis.set_title(
                "Visual annotation: green soil / pink paved"
                if not overlay
                else (
                    f"Pits: {primary['supported_soil']} supported / "
                    f"{primary['paved_conflict']} conflict / {primary['uncertain']} uncertain"
                )
            )
        fig.suptitle(
            case["case"]
            + " | visual interpretation, not expert ground truth | boundary uncertainty 0.25 m"
        )
        fig.savefig(out / f"{case['case']}-audit.png", dpi=150)
        plt.close(fig)
        print(
            json.dumps(
                {k: v for k, v in row.items() if k != "primary"}
                | {"counts": {k: v for k, v in primary.items() if k != "placements"}},
                ensure_ascii=False,
            ),
            flush=True,
        )
    (out / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.annotations, args.runs, args.out)
