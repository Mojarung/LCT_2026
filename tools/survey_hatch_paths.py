"""Aggregate HATCH paths locally; never write CAD coordinates to the report."""
# ruff: noqa: INP001, T201, SLF001 - research probe of the geometry adapter

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import shapely
from ezdxf.entities.boundary_paths import ArcEdge, EdgePath, PolylinePath

from green.infrastructure.cad.hatch_geometry import HatchGeometryError
from green.infrastructure.cad.reader import EzdxfSceneReader, _Walker

if TYPE_CHECKING:
    from collections.abc import Callable

    from ezdxf.entities import DXFGraphic
    from ezdxf.entities.polygon import DXFPolygon
    from shapely.geometry.base import BaseGeometry

    GeometryResult = tuple[BaseGeometry | None, float | None]
    GeometryReader = Callable[[_Walker, DXFGraphic], GeometryResult]


def gap_shapes(counts: Counter[str], entity: DXFPolygon) -> None:
    for path in entity.paths:
        if isinstance(path, PolylinePath):
            counts[f"gap_path_vertices:{len(path.vertices)}"] += 1
        elif isinstance(path, EdgePath):
            for edge in path.edges:
                if isinstance(edge, ArcEdge):
                    span = edge.end_angle - edge.start_angle
                    counts[f"gap_arc_span_deg:{span}"] += 1


def probe(counts: Counter[str], original: GeometryReader) -> GeometryReader:
    def inspect(walker: _Walker, entity: DXFGraphic) -> GeometryResult:
        if entity.dxftype() not in {"HATCH", "MPOLYGON"}:
            return original(walker, entity)
        counts["hatches"] += 1
        counts[f"style:{entity.dxf.hatch_style}"] += 1
        for path in entity.paths:
            counts[f"flags:{path.path_type_flags}"] += 1
            if isinstance(path, PolylinePath):
                counts["bulge_path" if path.has_bulge() else "straight_path"] += 1
                counts[f"polyline_closed:{bool(path.is_closed)}"] += 1
            elif isinstance(path, EdgePath):
                counts.update(type(edge).__name__ for edge in path.edges)
        try:
            geometry, error = original(walker, entity)
        except HatchGeometryError as exc:
            counts[f"conversion_gap:{exc}"] += 1
            gap_shapes(counts, entity)
            raise
        if geometry is None:
            counts["unreadable"] += 1
        else:
            counts["invalid_topology" if not geometry.is_valid else "valid_topology"] += 1
            if not geometry.is_valid:
                reason = shapely.is_valid_reason(geometry).split("[")[0]
                counts[f"invalid:{reason}"] += 1
            if error is None:
                counts["unbounded_conversion"] += 1
        return geometry, error

    return inspect


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = []
    original = _Walker._geometry
    for source in args.sources:
        counts: Counter[str] = Counter()
        begin = time.perf_counter()
        with patch.object(_Walker, "_geometry", probe(counts, original)):
            scene = EzdxfSceneReader().read(source)
        row = {
            "name": source.name,
            "source_sha256": scene.source_sha256,
            "counts": dict(sorted(counts.items())),
            "features": len(scene.features),
            "unbounded_features": sum(f.geometry_error_m is None for f in scene.features),
            "geometry_gaps": dict(
                Counter(
                    {
                        gap.reason: sum(
                            g.count
                            for g in scene.read_diagnostics.geometry_gaps
                            if g.reason == gap.reason
                        )
                        for gap in scene.read_diagnostics.geometry_gaps
                    }
                )
            ),
            "seconds": round(time.perf_counter() - begin, 4),
        }
        print(row, flush=True)
        rows.append(row)
    args.output.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
