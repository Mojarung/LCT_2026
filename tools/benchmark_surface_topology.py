"""Compare surface policies on declared synthetic materials and missing evidence."""
# ruff: noqa: INP001, T201 - standalone benchmark, no customer geometry

from __future__ import annotations

import itertools
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path

import shapely
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, Point, box

from green.application.surfaces import Material, build_surface_map
from green.domain.objects import Feature, ObjectClass, SourceRef, TextLabel

ROOT = Path(__file__).resolve().parents[1]
UNKNOWN, PAVED, SOIL = Material.UNKNOWN, Material.PAVED, Material.SOIL


@dataclass(frozen=True)
class Case:
    name: str
    features: list[Feature]
    labels: list[TextLabel]
    extent: shapely.Geometry
    probes: list[tuple[float, float, Material]]


def feature(kind: ObjectClass, geometry: shapely.Geometry) -> Feature:
    return Feature(
        SourceRef("synthetic", "0", kind.value), "unfamiliar", geometry, object_class=kind
    )


def label(text: str, x: float, y: float) -> TextLabel:
    return TextLabel(SourceRef("synthetic", "0", text), "unfamiliar", x, y, text)


def cases() -> list[Case]:
    extent = box(-5, -5, 105, 45)
    border = feature(ObjectClass.CURB, box(0, 0, 100, 40).boundary)
    lawn = label("ГАЗОН", 5, 5)
    return [
        Case("no-boundary", [], [lawn], extent, [(7, 5, UNKNOWN), (90, 5, UNKNOWN)]),
        Case(
            "project-boundary",
            [feature(ObjectClass.WORK_BOUNDARY, box(0, 0, 100, 40))],
            [lawn],
            extent,
            [(7, 5, UNKNOWN)],
        ),
        Case(
            "tree-in-grate",
            [border, feature(ObjectClass.EXISTING_TREE, Point(5, 5))],
            [],
            extent,
            [(5.1, 5.1, UNKNOWN), (50, 5, UNKNOWN)],
        ),
        Case(
            "conflicting-labels",
            [border],
            [lawn, label("А", 95, 5)],
            extent,
            [(7, 5, UNKNOWN), (94, 5, UNKNOWN)],
        ),
        Case(
            "closed-long-region",
            [border],
            [lawn],
            extent,
            [(7, 5, SOIL), (90, 35, SOIL), (102, 5, UNKNOWN)],
        ),
        Case(
            "open-outer-border",
            [feature(ObjectClass.CURB, LineString([(0, 1), (0, 40), (100, 40), (100, 0), (1, 0)]))],
            [lawn],
            extent,
            [(7, 5, UNKNOWN)],
        ),
        Case(
            "unlabelled-inner-hole",
            [border, feature(ObjectClass.CURB, box(10, 10, 15, 15).boundary)],
            [lawn],
            extent,
            [(7, 5, SOIL), (12, 12, UNKNOWN), (90, 35, SOIL)],
        ),
        Case(
            "divided-materials",
            [border, feature(ObjectClass.PAVEMENT_EDGE, LineString([(50, 0), (50, 40)]))],
            [lawn, label("А", 95, 5)],
            extent,
            [(7, 5, SOIL), (75, 5, PAVED), (75, 35, PAVED)],
        ),
        Case(
            "unfinished-divider",
            [border, feature(ObjectClass.PAVEMENT_EDGE, LineString([(50, 0), (50, 35)]))],
            [lawn],
            extent,
            [(7, 5, UNKNOWN), (70, 5, UNKNOWN)],
        ),
        Case(
            "explicit-lawn",
            [feature(ObjectClass.LAWN, box(0, 0, 100, 40))],
            [],
            extent,
            [(7, 5, SOIL), (90, 35, SOIL)],
        ),
        Case(
            "explicit-pavement",
            [feature(ObjectClass.SIDEWALK, box(0, 0, 100, 40))],
            [lawn],
            extent,
            [(7, 5, PAVED), (90, 35, PAVED)],
        ),
        Case(
            "uncertain-label-position",
            [replace(border, geometry_error_m=0.2)],
            [label("ГАЗОН", 0.1, 10)],
            extent,
            [(7, 10, UNKNOWN)],
        ),
    ]


def main() -> None:
    rows = []
    for mode, cell, angle, offset in itertools.product(
        ("distance", "closed_faces"), (0.25, 0.5, 1.0), (0, 23, 91), (0, 1_000_000)
    ):

        def transform(
            geometry: shapely.Geometry, a: int = angle, shift: int = offset
        ) -> shapely.Geometry:
            return translate(rotate(geometry, a, origin=(0, 0)), shift, -shift)

        for case in cases():
            features = [replace(f, geometry=transform(f.geometry)) for f in case.features]
            labels = []
            for source in case.labels:
                point = transform(Point(source.x, source.y))
                labels.append(replace(source, x=point.x, y=point.y))
            begin = time.perf_counter()
            surface = build_surface_map(
                features, labels, transform(case.extent), cell, inference_mode=mode
            )
            points = shapely.points([transform(Point(x, y)).coords[0] for x, y, _ in case.probes])
            actual = surface.material(points).tolist() if surface else [UNKNOWN] * len(points)
            expected = [m for _, _, m in case.probes]
            rows.append(
                {
                    "case": case.name,
                    "mode": mode,
                    "cell_m": cell,
                    "rotation_deg": angle,
                    "translation_m": offset,
                    "expected": expected,
                    "actual": actual,
                    "false_soil": sum(
                        got == SOIL and want != SOIL
                        for got, want in zip(actual, expected, strict=True)
                    ),
                    "missed_soil": sum(
                        got != SOIL and want == SOIL
                        for got, want in zip(actual, expected, strict=True)
                    ),
                    "mismatches": sum(
                        got != want for got, want in zip(actual, expected, strict=True)
                    ),
                    "seconds": round(time.perf_counter() - begin, 5),
                }
            )
    totals = {}
    for mode in ("distance", "closed_faces"):
        subset = [r for r in rows if r["mode"] == mode]
        totals[mode] = {
            key: sum(r[key] for r in subset)
            for key in ("false_soil", "missed_soil", "mismatches", "seconds")
        }
        totals[mode]["runs"] = len(subset)
        totals[mode]["probes"] = sum(len(r["actual"]) for r in subset)
    result = {
        "scope": (
            "Synthetic oracle: declared materials or explicitly insufficient evidence. "
            "Not measured DXF semantic accuracy or survey completeness."
        ),
        "summary": totals,
        "rows": rows,
    }
    (ROOT / "docs/research/verified-pipeline/surface_topology_comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(totals, indent=2))


if __name__ == "__main__":
    main()
