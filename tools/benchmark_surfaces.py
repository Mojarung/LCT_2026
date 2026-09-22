"""Synthetic surface-policy ablation; known probes, no customer-data accuracy claims."""

from __future__ import annotations

import itertools
import json
import time
from pathlib import Path

import shapely
from shapely.affinity import translate
from shapely.geometry import Point, box

from green.application.surfaces import build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel

ROOT = Path(__file__).resolve().parents[1]
UNKNOWN, PAVED, SOIL = 0, 1, 2


def label(text: str, x: float, y: float) -> TextLabel:
    return TextLabel(SourceRef("synthetic", "0", text), "universal", x, y, text)


def feature(kind: ObjectClass, geometry: shapely.Geometry) -> Feature:
    return Feature(
        SourceRef("synthetic", "0", kind.value), "universal", geometry, object_class=kind
    )


def scenarios() -> list[tuple]:
    return [
        (
            "blank-region",
            [],
            [label("ГАЗОН", 10, 10), label("А", 10, 90)],
            box(0, 0, 200, 100),
            [(12, 10, SOIL), (150, 10, UNKNOWN), (12, 90, PAVED)],
        ),
        (
            "conflict",
            [],
            [label("ГАЗОН", 10, 10), label("А", 10, 10)],
            box(0, 0, 30, 30),
            [(10, 10, UNKNOWN), (15, 10, UNKNOWN)],
        ),
        (
            "explicit-lawn-with-hole",
            [feature(ObjectClass.LAWN, box(0, 0, 20, 20).difference(box(8, 8, 12, 12)))],
            [],
            box(-5, -5, 25, 25),
            [(5, 5, SOIL), (10, 10, UNKNOWN), (-2, -2, UNKNOWN)],
        ),
        (
            "isolated-tree",
            [feature(ObjectClass.EXISTING_TREE, Point(10, 10))],
            [label("А", 90, 90)],
            box(0, 0, 100, 100),
            [(20, 10, UNKNOWN), (90, 90, PAVED)],
        ),
        (
            "explicit-pavement",
            [feature(ObjectClass.SIDEWALK, box(0, 0, 20, 20))],
            [label("ГАЗОН", 10, 10), label("А", 25, 25)],
            box(-5, -5, 30, 30),
            [(10, 10, PAVED)],
        ),
    ]


def main() -> None:
    rows = []
    for cell, reach, ambiguity, shift in itertools.product(
        (0.25, 0.5, 1.0),
        (15.0, 30.0, 60.0, 1_000_000.0),
        (0.0, 1.0),
        ((0, 0), (0.13, 0.29), (1_000_000, -500_000)),
    ):
        begin = time.perf_counter()
        failed, probes = [], 0
        for name, features, labels, extent, expected in scenarios():
            dx, dy = shift
            moved_features = [
                feature(f.object_class, translate(f.geometry, dx, dy)) for f in features
            ]
            moved_labels = [label(lab.text, lab.x + dx, lab.y + dy) for lab in labels]
            surface = build_surface_map(
                moved_features,
                moved_labels,
                translate(extent, dx, dy),
                cell,
                max_distance_m=reach,
                ambiguity_m=ambiguity,
                tree_distance_m=2.0 if reach < 1_000_000 else reach,
            )
            points = shapely.points([(x + dx, y + dy) for x, y, _ in expected])
            actual = surface.material(points).tolist() if surface else [UNKNOWN] * len(points)
            for i, (got, (_, _, want)) in enumerate(zip(actual, expected, strict=True)):
                probes += 1
                if got != want:
                    failed.append({"scene": name, "probe": i, "expected": want, "actual": got})
        rows.append(
            {
                "cell_m": cell,
                "reach_m": reach,
                "ambiguity_m": ambiguity,
                "translation": shift,
                "probes": probes,
                "failures": failed,
                "seconds": round(time.perf_counter() - begin, 4),
            }
        )
    result = {
        "scope": "Synthetic material probes; not real-world recognition accuracy. Unlimited is an ablation of reach, not the original implementation.",
        "variants": rows,
        "summary": {
            "variants": len(rows),
            "probes": sum(r["probes"] for r in rows),
            "passing_variants": sum(not r["failures"] for r in rows),
        },
    }
    target = ROOT / "docs/research/verified-pipeline/surface_ablation.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))
    for reach in (15.0, 30.0, 60.0, 1_000_000.0):
        subset = [r for r in rows if r["reach_m"] == reach]
        print({"reach_m": reach, "failed_probes": sum(len(r["failures"]) for r in subset)})


if __name__ == "__main__":
    main()
